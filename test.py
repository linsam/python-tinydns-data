#!/usr/bin/env python3
# This program makes some hard-coded output in the style of cdb-dump. It
# should be piped directly to cdbmake or cdb

import sys
import time
import os

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
RR_TYPE_AXFR = 252

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
    byte_count = bits >> 3
    res = []
    for i in range(byte_count):
        res.append(u & 0xff)
        u >>= 8
    res.reverse()
    return bytes(res)

def u16_to_bytes(u16):
    return u_to_bytes(u16, 16)

def u32_to_bytes(u32):
    return u_to_bytes(u32, 32)

def u64_to_bytes(u64):
    return u_to_bytes(u64, 64)

#print(bytes(u32_to_bytes(ipv4_to_u32(address))).hex(), flush=True)
#out.write(bytes(u32_to_bytes(ipv4_to_u32(address))))

def name_to_labels(name):
    parts = name.split('.')
    return parts

def labels_to_dns(labels):
    # TODO: Handle unicde to punicode or whatever
    res = []
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


with open("data") as data:
    for line in data:
        line = line.rstrip()
        if len(line) == 0 or line[0] == '#':
            continue
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
            rname = ".".join(list(reversed(address.split('.'))) + ['in-addr','arpa'])
            data = labels_to_dns(name_to_labels(name))
            out.write(make_record(rname, RR_TYPE_PTR, loc, ttl, ttd, data))
        elif rtype == '-':
            # Disabled A record
            continue
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
        elif rtype == '%':
            raise Exception("% records are TBD")
        else:
            raise Exception("Unknown record type '{}'".format(rtype))


# Finally, after the last record is an extra newline
out.write(b'\n')
