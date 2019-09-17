#!/usr/bin/env python3
# This program makes some hard-coded output in the style of cdb-dump. It
# should be piped directly to cdbmake or cdb

# first up, an ipv4 record
name = "test.example.com"
ttl = 86400
address = "192.168.1.42"

import sys
out = sys.stdout.buffer


def ipv4_to_u32(ipv4):
    parts = ipv4.split('.')
    if len(parts) != 4:
        raise Exception("invalid IPv4 address")
    res = 0
    for part in parts:
        res <<=8
        res |= int(part)
    return res

def u32_to_bytes(u32):
    res = []
    while u32:
        res.append(u32 & 0xff)
        u32 >>= 8
    res.reverse()
    return bytes(res)

#print(bytes(u32_to_bytes(ipv4_to_u32(address))).hex(), flush=True)
#out.write(bytes(u32_to_bytes(ipv4_to_u32(address))))

def name_to_labels(name):
    parts = name.split('.')
    return parts

def labels_to_dns(labels):
    # TODO: Handle unicde to punicode or whatever
    res = []
    for part in labels:
        p = part.encode('ascii')
        l = len(part)
        if l == 0 or l > 255:
            raise Exception("bad label length {}".format(l))
        res.append(bytes([l]) + p)
    res.append(bytes([0])) # NULL aka root label
    return b''.join(res)

key = labels_to_dns(name_to_labels(name))
value = bytes([0,1, ord('='), 0, 1, 0x51, 0x80, 0, 0, 0, 0, 0, 0, 0, 0]) + u32_to_bytes(ipv4_to_u32(address))
klen = len(key)
vlen = len(value)
record = "+{},{}:".format(klen,vlen).encode('ascii') + key + b'->' + value + bytes((0x0a,))
#print(record)
out.write(record)

# Finally, after the last record is an extra newline
out.write(b'\n')
