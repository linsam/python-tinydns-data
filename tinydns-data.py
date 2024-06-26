#!/usr/bin/env python3
# This program makes some hard-coded output in the style of cdb-dump. It
# should be piped directly to cdbmake or cdb

import sys
import time
import os
import codecs

out = sys.stdout.buffer

default_TTL = "86400"
#timestr = str(int(time.time())) # used for default SOA serial number
timestr = str(int(os.stat('data').st_mtime)) # used for default SOA serial number

RR_TYPE_A = 1
RR_TYPE_NS = 2
RR_TYPE_CNAME = 5
RR_TYPE_SOA = 6
RR_TYPE_PTR = 12
RR_TYPE_MX = 15
RR_TYPE_TXT = 16
RR_TYPE_AAAA = 28
RR_TYPE_SRV = 33
RR_TYPE_NAPTR = 35
RR_TYPE_CERT = 37
RR_TYPE_DS = 43
RR_TYPE_SSHFP = 44
RR_TYPE_TLSA = 52
RR_TYPE_OPENPGPKEY = 61
RR_TYPE_SVCB = 64
RR_TYPE_HTTPS = 65
RR_TYPE_AXFR = 252
RR_TYPE_CAA = 257

def ipv4_to_u32(ipv4):
    parts = ipv4.split('.')
    if len(parts) != 4:
        raise Exception("invalid IPv4 address")
    res = 0
    for part in parts:
        res <<=8
        res |= int(part)
    return res

def u_to_bytes(u, bits):
    if bits & 0x7:
        raise Exception("Extra bits; not byte aligned")
    if u >= 2**bits:
        raise Exception("Given number {} doesn't fit in {} bits".format(u, bits))
    byte_count = bits >> 3
    res = []
    for i in range(byte_count):
        res.append(u & 0xff)
        u >>= 8
    res.reverse()
    return bytes(res)

def u8_to_bytes(u8):
    return u_to_bytes(u8, 8)

def u16_to_bytes(u16):
    return u_to_bytes(u16, 16)

def u32_to_bytes(u32):
    return u_to_bytes(u32, 32)

def u64_to_bytes(u64):
    return u_to_bytes(u64, 64)

#print(bytes(u32_to_bytes(ipv4_to_u32(address))).hex(), flush=True)
#out.write(bytes(u32_to_bytes(ipv4_to_u32(address))))

def name_to_labels(name):
    if name.endswith('.'):
        name = name[:-1]
    parts = name.split('.')
    return parts

def labels_to_dns(labels):
    # TODO: Handle unicde to punicode or whatever
    res = []
    if len(labels[-1]) == 0:
        # Allow optional trailing NULL label (e.g. a name ending in a '.' from
        # name_to_labels()), we'll add the trailing NULL back at the end.
        # Actually, name_to_labels already strips that, but other things might
        # not. Also, this fixes the special case of just the root label.
        labels = labels[:-1]
    for part in labels:
        if isinstance(part, str):
            p = part.encode('ascii')
        else:
            p = part
        l = len(part)
        if l == 0 or l > 255:
            raise Exception("bad label length {}".format(l))
        res.append(bytes([l]) + p)
    res.append(bytes([0])) # NULL aka root label
    return b''.join(res)

def deescape_text(text):
    """Given text with escaped octal data, convert the octal data to equivalent bytes.
    For example:
        "v=spf1 ip4\\072198.51.100.33/29" -> "v=spf1 ip4:198.51.100.33/29"
    Assumes the text is ASCII
    """
    # Note: The \\ shown above is a single '\', it's escaped here so it shows
    # correctly in printed docstrings.
    # TODO: Support utf8? I haven't found anything indicating that text
    # records must be 7-bit safe, or ascii instead of binary.
    text = text.encode('ascii')
    res = b''
    while text != b'':
        if not text[:1] == b'\\':
            res += text[:1]
            text = text[1:]
        else:
            num = int(text[1:4], 8)
            text = text[4:]
            res += bytes([num])
    return res

def overlay(given, defaults):
    """Pull elements from given until we run out, then use defaults
    also, use defaults if an element in given is empty (that is, None or '')
    """
    l1 = len(given)
    l2 = len(defaults)
    rem = l2 - l1
    res = []
    for i in range(min(l1,l2)):
        if given[i] in [None, '']:
            res.append(defaults[i])
        else:
            res.append(given[i])
    if l1 < l2:
        res.extend(defaults[l2 - rem:])
    return res

def make_record(name, type_, loc, ttl, ttd, data):
    key = labels_to_dns(name_to_labels(name))
    if loc is None:
        value = u16_to_bytes(type_) + b'=' + u32_to_bytes(ttl) + u64_to_bytes(ttd) + data
    else:
        loc = loc.encode('ascii')
        if len(loc) != 2:
            raise Exception("Bad loc")
        value = u16_to_bytes(type_) + b'>' + loc + u32_to_bytes(ttl) + u64_to_bytes(ttd) + data
    klen = len(key)
    vlen = len(value)
    record = "+{},{}:".format(klen,vlen).encode('ascii') + key + b'->' + value + bytes((0x0a,))
    return record

delegates4 = []
delegates6 = []

def getSubDelegates4(address):
    results = []
    for delegation in delegates4:
        range_, target, octets = delegation
        start, end = range_
        if start <= address and address <= end:
            results.append((target, octets))
    return results

def getSubDelegates6(address):
    results = []
    for delegation in delegates6:
        range_, target, octets = delegation
        start, end = range_
        if start <= address and address <= end:
            results += (target, octets)
    return results

def makeReverseRecords4(address, target, loc, ttl, ttd):
    parts = address.split('.')
    rparts = list(reversed(parts))
    i_address = (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + (int(parts[3]))
    data = labels_to_dns(name_to_labels(target))

    # do any sub-delegation formats (e.g. DeGroot, RFC2317))
    did_delegate = False
    for base, octets in getSubDelegates4(i_address):
        rname = ".".join(rparts[:octets] + [base])
        out.write(make_record(rname, RR_TYPE_PTR, loc, ttl, ttd, data))
        did_delegate = True
    if not did_delegate:
        # Do the normal record if we didn't do anything special
        rname = ".".join(rparts + ['in-addr','arpa'])
        out.write(make_record(rname, RR_TYPE_PTR, loc, ttl, ttd, data))

def processLine(line):
        line = line.rstrip()
        if len(line) == 0 or line[0] == '#':
            return
        rtype = line[0]
        line = line[1:]
        if rtype == '+':
            # Address
            defaults = [None, None, default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)
            name = fields[0]
            address = fields[1]
            ttl = int(fields[2])
            ttd = int(fields[3],16)
            loc = fields[4]
            data = u32_to_bytes(ipv4_to_u32(address))
            out.write(make_record(name, RR_TYPE_A, loc, ttl, ttd, data))
        elif rtype == '3':
            # IPv6 address
            defaults = [None, None, default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)
            name = fields[0]
            address = fields[1]
            ttl = int(fields[2])
            ttd = int(fields[3],16)
            loc = fields[4]
            data = codecs.decode(address, 'hex')
            if len(data) != 16:
                raise Exception("hex isn't 16 bytes IPv6 address")
            out.write(make_record(name, RR_TYPE_AAAA, loc, ttl, ttd, data))
        elif rtype == '=':
            # Address
            defaults = [None, None, default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)
            name = fields[0]
            address = fields[1]
            ttl = int(fields[2])
            ttd = int(fields[3],16)
            loc = fields[4]
            # First, the A record
            data = u32_to_bytes(ipv4_to_u32(address))
            out.write(make_record(name, RR_TYPE_A, loc, ttl, ttd, data))
            # Next, the PTR record
            makeReverseRecords4(address, name, loc, ttl, ttd)
        elif rtype == '6':
            # IPv6 address with PTR
            defaults = [None, None, default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)
            name = fields[0]
            address = fields[1]
            ttl = int(fields[2])
            ttd = int(fields[3],16)
            loc = fields[4]
            # AAAA record
            data = codecs.decode(address, 'hex')
            if len(data) != 16:
                raise Exception("hex isn't 16 bytes IPv6 address")
            out.write(make_record(name, RR_TYPE_AAAA, loc, ttl, ttd, data))

            raddress = '.'.join(reversed(list(address.lower())))
            data = labels_to_dns(name_to_labels(name))
            # PTR record for ip6.arpa, to be compatible with old stuff? The
            # dbndns package does this, presumably from the fefe patch.
            rname = raddress + '.ip6.arpa'
            out.write(make_record(rname, RR_TYPE_PTR, loc, ttl, ttd, data))
            # PTR record for ip6.int, the normal one
            rname = raddress + '.ip6.int'
            out.write(make_record(rname, RR_TYPE_PTR, loc, ttl, ttd, data))
        elif rtype == '-':
            # Disabled A record
            return
        elif rtype == '^':
            # PTR
            defaults = [None, None, default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)
            name = fields[0]
            destname = fields[1]
            ttl = int(fields[2])
            ttd = int(fields[3],16)
            loc = fields[4]
            data = labels_to_dns(name_to_labels(destname))
            out.write(make_record(name, RR_TYPE_PTR, loc, ttl, ttd, data))
        elif rtype == 'C':
            # CNAME (like PTR)
            defaults = [None, None, default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)
            name = fields[0]
            destname = fields[1]
            ttl = int(fields[2])
            ttd = int(fields[3],16)
            loc = fields[4]
            data = labels_to_dns(name_to_labels(destname))
            out.write(make_record(name, RR_TYPE_CNAME, loc, ttl, ttd, data))
        elif rtype == 'Z':
            # Zone (SOA)

            # The defaults are very round numbers in hex...
            # Note: Although the global default ttl is 86400 (1 day), the SOA
            # TTL defaults to 2560, like the minttl value.
            defaults = [None, "", "", timestr, "16384", "2048", "1048576", "2560", "2560", "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            primary = labels_to_dns(name_to_labels(fields[1]))
            hostmaster = labels_to_dns(name_to_labels(fields[2]))
            serial = int(fields[3])
            refresh = int(fields[4])
            retry = int(fields[5])
            expire = int(fields[6])
            minttl = int(fields[7])
            ttl = int(fields[8])
            ttd = int(fields[9],16)
            loc = fields[10]
            data = primary + hostmaster + u32_to_bytes(serial) + u32_to_bytes(refresh) + u32_to_bytes(retry) + u32_to_bytes(expire) + u32_to_bytes(minttl)
            out.write(make_record(name, RR_TYPE_SOA, loc, ttl, ttd, data))
        elif rtype == '&':
            # NS record

            # Note: default TTL for NS is 3 days
            defaults = [None, "", "", "259200", "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            address = fields[1]
            server = fields[2]
            ttl = int(fields[3])
            ttd = int(fields[4],16)
            loc = fields[5]

            if server == "":
                server = "ns." + name
            elif not '.' in server:
                server = server + ".ns." + name

            data = labels_to_dns(name_to_labels(server))
            out.write(make_record(name, RR_TYPE_NS, loc, ttl, ttd, data))
            if address != "":
                data = u32_to_bytes(ipv4_to_u32(address))
                out.write(make_record(server, RR_TYPE_A, loc, ttl, ttd, data))
        elif rtype == '.':
            # Simple SOA. Same format as &
            # Note: default TTL for NS is 3 days
            defaults = [None, "", "", "259200", "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            address = fields[1]
            server = fields[2]
            ttl = int(fields[3])
            ttd = int(fields[4],16)
            loc = fields[5]

            if server == "":
                server = "ns." + name
            elif not '.' in server:
                server = server + ".ns." + name
            hostmaster = "hostmaster." + name

            serial = int(timestr)
            refresh = 0x4000
            retry = 0x800
            expire = 0x100000
            minttl = 0xa00
            primary = labels_to_dns(name_to_labels(server))
            hostmaster = labels_to_dns(name_to_labels(hostmaster))
            # SOA record. Note that original tinydns-data forces TTL of SOA to
            # 2560 no matter what here. If you want custom TTL for SOA, you
            # need a Z record.
            data = primary + hostmaster + u32_to_bytes(serial) + u32_to_bytes(refresh) + u32_to_bytes(retry) + u32_to_bytes(expire) + u32_to_bytes(minttl)
            out.write(make_record(name, RR_TYPE_SOA, loc, 2560, ttd, data))
            # NS record
            data = labels_to_dns(name_to_labels(server))
            out.write(make_record(name, RR_TYPE_NS, loc, ttl, ttd, data))
            if address != "":
                # A record
                data = u32_to_bytes(ipv4_to_u32(address))
                out.write(make_record(server, RR_TYPE_A, loc, ttl, ttd, data))
        elif rtype == '@':
            # MX record

            defaults = [None, "", "", "0", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            address = fields[1]
            server = fields[2]
            priority = int(fields[3])
            ttl = int(fields[4])
            ttd = int(fields[5])
            loc = fields[6]

            if server == "":
                server = "mx." + name
            elif not '.' in server:
                server = server + ".mx." + name

            lserver = labels_to_dns(name_to_labels(server))
            # MX record
            data = u16_to_bytes(priority) + lserver
            out.write(make_record(name, RR_TYPE_MX, loc, ttl, ttd, data))
            if address != "":
                # A record
                data = u32_to_bytes(ipv4_to_u32(address))
                out.write(make_record(server, RR_TYPE_A, loc, ttl, ttd, data))
        elif rtype == "'":
            # TXT record

            defaults = [None, "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            text = fields[1]
            ttl = int(fields[2])
            ttd = int(fields[3])
            loc = fields[4]

            text = deescape_text(text)
            strlist = []
            while len(text):
                strlist.append(text[:127])
                text = text[127:]
            data = labels_to_dns(strlist)[:-1] # chop off the trailing NULL label, shouldn't be in TXT records
            out.write(make_record(name, RR_TYPE_TXT, loc, ttl, ttd, data))
        elif rtype == "S":
            # SRV record

            defaults = [None, "", "", None, "1", "0", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            address = fields[1]
            server = fields[2]
            port = int(fields[3])
            priority = int(fields[4])
            weight = int(fields[5])
            ttl = int(fields[6])
            ttd = int(fields[7])
            loc = fields[8]

            # SRV record
            lserver = labels_to_dns(name_to_labels(server))
            data = u16_to_bytes(priority) + u16_to_bytes(weight) + u16_to_bytes(port) + lserver
            out.write(make_record(name, RR_TYPE_SRV, loc, ttl, ttd, data))
            if address != "":
                # TODO: support IPv6?
                # A record
                data = u32_to_bytes(ipv4_to_u32(address))
                out.write(make_record(server, RR_TYPE_A, loc, ttl, ttd, data))
        elif rtype == "N":
            # NAPTR record

            defaults = [None, "", "0", "", "", "", "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            order = int(fields[1])
            preference = int(fields[2])
            flags = fields[3]
            service = fields[4]
            regexp = fields[5]
            replacement = fields[6]
            ttl = int(fields[7])
            ttd = int(fields[8])
            loc = fields[9]

            flags = labels_to_dns([deescape_text(flags)])[:-1]
            service = labels_to_dns([deescape_text(service)])[:-1]
            regexp = labels_to_dns([deescape_text(regexp)])[:-1]
            replacement = labels_to_dns(name_to_labels(replacement))

            data = u16_to_bytes(order) + u16_to_bytes(preference) + flags + service + regexp + replacement
            out.write(make_record(name, RR_TYPE_NAPTR, loc, ttl, ttd, data))
        elif rtype == "c":
            # CAA record

            defaults = [None, "0", "", "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            flag = int(fields[1])
            tag = fields[2]
            value = fields[3]
            ttl = int(fields[4])
            ttd = int(fields[5])
            loc = fields[6]

            # Tag needs to include length
            tag = labels_to_dns([deescape_text(tag)])[:-1]
            # Value does _NOT_ include length
            value = deescape_text(value)

            data = u8_to_bytes(flag) + tag + value
            out.write(make_record(name, RR_TYPE_CAA, loc, ttl, ttd, data))
        elif rtype == 't':
            # TLSA record

            defaults = [None, "", "", "", "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            usage = int(fields[1])
            selector = int(fields[2])
            match_type = int(fields[3])
            cert_data = fields[4]
            ttl = int(fields[5])
            ttd = int(fields[6])
            loc = fields[7]

            cert_data = codecs.decode(cert_data, 'hex')

            data = u8_to_bytes(usage) + u8_to_bytes(selector) + u8_to_bytes(match_type) + cert_data
            out.write(make_record(name, RR_TYPE_TLSA, loc, ttl, ttd, data))
        elif rtype == 'd':
            # DS record

            defaults = [None, "", "", "", "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            tag = int(fields[1])
            algorithm = int(fields[2])
            digest_type = int(fields[3])
            digest_data = fields[4]
            ttl = int(fields[5])
            ttd = int(fields[6])
            loc = fields[7]

            digest_data = codecs.decode(digest_data, 'hex')

            data = u16_to_bytes(tag) + u8_to_bytes(algorithm) + u8_to_bytes(digest_type) + digest_data
            out.write(make_record(name, RR_TYPE_DS, loc, ttl, ttd, data))
        elif rtype == 's':
            # SSHFP record

            defaults = [None, None, None, "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            algorithm = int(fields[1])
            fingerprint_type = int(fields[2])
            fingerprint_data = fields[3]
            ttl = int(fields[4])
            ttd = int(fields[5])
            loc = fields[6]

            fingerprint_data = codecs.decode(fingerprint_data, 'hex')

            data = u8_to_bytes(algorithm) + u8_to_bytes(fingerprint_type) + fingerprint_data
            out.write(make_record(name, RR_TYPE_SSHFP, loc, ttl, ttd, data))
        elif rtype == 'V' or rtype == 'H':
            # SVCB record

            defaults = [None, None, "0", "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            destname = fields[1]
            priority = int(fields[2])
            params = fields[3]
            ttl = int(fields[4])
            ttd = int(fields[5])
            loc = fields[6]

            if priority==0 and len(params) != 0:
                # TODO: Warn? There is no param in current spec where this is valid. Can't make it an error since future specs could allow it
                pass
            svcbkeys = {
                "mandatory": 0,
                "alpn": 1,
                "no-default-alpn": 2,
                "port": 3,
                "ipv4hint": 4,
                "ipv6hint": 6,
                }
            def get_key_num(key: str) -> int:
                if key in svcbkeys:
                    return svcbkeys[key]
                elif key.startswith("key"):
                    return int(key[3:],10)
                else:
                    raise Exception("Unknown SVCB param {}".format(key))
            paramset = {}
            mandatories = []
            for param in params.split(' '):
                if len(param) == 0:
                    # empty params string or multiple spaces
                    continue
                if '=' in param:
                    keyname,value = param.split('=',1)
                else:
                    keyname,value = param, "" # Could do none if it becomes important do differentiate between an empty assignment and no assignment
                key = get_key_num(keyname)
                if key in paramset:
                    raise Exception("Duplicate param {}".format(keyname))
                # TODO: Maybe have a lookup table of functions?
                if keyname == "mandatory":
                    subkeynames = value.split(',')
                    subvalue = []
                    for subkeyname in subkeynames:
                        if subkeyname in svcbkeys:
                            subvalue.append(svcbkeys[subkeyname])
                        elif subkeyname.startswith("key"):
                            subvalue.append(int(subkeyname[3:],10))
                        else:
                            raise Exception("Unknown SVCB param in mandatory section: {}".format(subkeyname))
                    subvalue.sort()
                    if subvalue[0] == 0:
                        # See RFC 9460 §8
                        raise Exception("The 'mandatory' key must not appear in it's own list (either as mandatory or as 'key0')")

                    # Save the set for final record validation
                    mandatories = subvalue

                    subvalue = b''.join(map(u16_to_bytes, subvalue))
                    paramset[key] = subvalue
                elif keyname == "alpn":
                    subkeynames = value.split(',')
                    subvalue = []
                    for subkeyname in subkeynames:
                        subkeyname = deescape_text(subkeyname)
                        if len(subkeyname) > 255:
                            raise Exception("Value too long: {}".format(subkeyname))
                        subvalue.append(u8_to_bytes(len(subkeyname)))
                        subvalue.append(subkeyname)
                    subvalue = b''.join(subvalue)
                    paramset[key] = subvalue
                elif keyname == "no-default-alpn":
                    if len(value):
                        raise Exception("no-default-alpn takes no value; but given {}", value)
                    paramset[key] = b''
                elif keyname == "port":
                    value = int(value)
                    paramset[key] = u16_to_bytes(value)
                elif keyname == "ipv4hint":
                    values=[]
                    value = value.split(',')
                    for subvalue in value:
                        values.append(u32_to_bytes(ipv4_to_u32(subvalue)))
                    paramset[key] = b''.join(values)
                elif keyname == "ipv6hint":
                    values=[]
                    value = value.split(',')
                    for subvalue in value:
                        data = codecs.decode(subvalue, 'hex')
                        if len(data) != 16:
                            raise Exception("hex isn't 16 bytes IPv6 address")
                        values.append(data)
                    paramset[key] = b''.join(values)
                elif keyname.startswith("key"):
                    keynum = int(keyname[3:], 10)
                    paramset[key] = deescape_text(value)
                else:
                    raise Exception("how did you get here? This should have been filtered prior")

            paramdata = []
            # Spec requires storage in ascending order by key
            paramkeys = sorted(paramset.keys())
            for key in paramkeys:
                value = paramset[key]
                paramdata.extend((u16_to_bytes(key), u16_to_bytes(len(value)), value))

            data = u16_to_bytes(priority) + labels_to_dns(name_to_labels(destname)) + b''.join(paramdata)
            # Verify that all mandatory fields are actually present
            for key in mandatories:
                if not key in paramkeys:
                    keyname = None
                    for k,v in svcbkeys.items():
                        if key == v:
                            keyname = k
                            break
                    if keyname:
                        keyname = "key{} ({})".format(key, keyname)
                    else:
                        keyname = "key{}".format(key)
                    raise Exception("{} listed as mandatory, but is not present in record".format(keyname))
                # TODO: Warn if rtype == 'H' and we found 'port' or 'no-default-alpn' listed in mandatory? These are 'SHOULD NOT' in the spec RFC9460§9¶5 and RFC9640§8¶8
            if rtype == 'V':
                out.write(make_record(name, RR_TYPE_SVCB, loc, ttl, ttd, data))
            elif rtype == 'H':
                out.write(make_record(name, RR_TYPE_HTTPS, loc, ttl, ttd, data))

        elif rtype == ":":
            # raw record

            defaults = [None, None, "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            rrtype = int(fields[1])
            text = fields[2]
            ttl = int(fields[3])
            ttd = int(fields[4])
            loc = fields[5]

            if rrtype in [RR_TYPE_AXFR, RR_TYPE_SOA, RR_TYPE_NS, RR_TYPE_CNAME, RR_TYPE_PTR, RR_TYPE_MX, 0]:
                # Note: I don't see a good reason why these are disallowed,
                # but they are in DJB's documentation and implementation
                raise Exception("RR type {} disallowed".format(rrtype))

            data = deescape_text(text)
            out.write(make_record(name, rrtype, loc, ttl, ttd, data))
        elif rtype == '/':
            # Sub-delegation type; modifies PTR generation and optionally
            # creates appropriate CNAME, NS and the NS's A records
            defaults = [None, None, "", "", default_TTL, "0", None]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            range_ = fields[1]
            nsname = fields[2]
            nsaddr = fields[3]
            ttl = int(fields[4])
            ttd = int(fields[5])
            loc = fields[6]

            if '/' in range_:
                # cidr
                base, prefix = range_.split('/')
                prefix = int(prefix)
                if not ( 24 < prefix and prefix < 32):
                    raise Exception("only prefixes between 24 and 32 make sense")
                parts = base.split('.')
                if len(parts) != 4:
                    raise Exception("Malformed IP address in field 1")
                addr = (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])
                mask = (1 << (32 - prefix)) - 1
                start = addr & ~mask
                end = addr | mask
            elif '-' in range_:
                # plain range
                parts = range_.split('.')
                if len(parts) != 4:
                    raise Exception("Malformed IP address in field 1")
                lsb_start, lsb_end = parts[3].split('-')
                start = (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(lsb_start)
                end = (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(lsb_end)
            else:
                raise Exceptino("Bad format for the range/cidr")
            delegates4.append(((start,end), name, 1))
            if len(nsname):
                # Add CNAME records
                for i in range(start, end + 1):
                    rtarget = "{}.{}.".format(i & 0xff, name)
                    rname = "{}.{}.{}.{}.in-addr.arpa.".format(
                            i & 0xff,
                            (i >> 8) & 0xff,
                            (i >> 16) & 0xff,
                            (i >> 24) & 0xff)
                    data = labels_to_dns(name_to_labels(rtarget))
                    out.write(make_record(rname, RR_TYPE_CNAME, loc, ttl, ttd, data))
                if nsname != '.':
                    # do NS record
                    data = labels_to_dns(name_to_labels(nsname))
                    out.write(make_record(name, RR_TYPE_NS, loc, ttl, ttd, data))
                    if nsaddr != "":
                        data = u32_to_bytes(ipv4_to_u32(nsaddr))
                        out.write(make_record(nsname, RR_TYPE_A, loc, ttl, ttd, data))


        elif rtype == '%':
            defaults = [None, ""]
            givenfields = line.split(':')
            fields = overlay(givenfields, defaults)

            name = fields[0]
            prefix = fields[1]

            name = name.encode('ascii')
            if len(name) != 2:
                raise Exception("Location must be 2 characters only (got {})".format(name))

            parts = prefix.split('.')
            if len(parts) > 4:
                raise Exception("Malformed location IPv4 prefix {}".format(prefix))
            prefix_bytes = b''
            for part in parts:
                prefix_bytes += bytes([int(part)])
            key = b'\0%' + prefix_bytes
            value = name
            klen = len(key)
            vlen = len(value)
            record = "+{},{}:".format(klen,vlen).encode('ascii') + key + b'->' + value + bytes((0x0a,))
            out.write(record)


        else:
            raise Exception("Unknown record type '{}'".format(rtype))

with open("data") as data:
    lineno = 0
    for line in data:
        lineno += 1
        try:
            processLine(line)
        except:
            print("Error encountered while processing input line {}:".format(lineno), file=sys.stderr)
            raise

# Finally, after the last record is an extra newline
out.write(b'\n')
