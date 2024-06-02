# Synopsis:

    ./tinydns-data.py | cdb -c data.cdb

or

    ./tinydns-data.py | cdbmake data.cdb data.cdb.tmp

tinydns-data.py will read the file named 'data' in the current directory (just
like the original tinydns-data). However, it doesn't have cdb capability
built-in and needs a helper to do the final conversion. This can be any helper
that understands the 'standard' cdb text representation, such as tinycdb's
'cdb' or freecdb's 'cdbmake'.


# Requirements:

* python3.x (tested on Python 3.6.8)
* tinycdb (for the cdb executable) or freecdb (for the cdbmake executable) (mostly tested with tinycdb 0.78 on Ubuntu 18.04)


# Supported record types:

* SOA
* NS
* A
* AAAA
* PTR
* MX
* CNAME
* TXT
* SRV
* NAPTR
* CAA
* TLSA
* DS
* SSHFP
* any other format specified raw

See the "File Format" section at the bottom for details.


# Project Rationale:

Of the format's I (the original author) have used to
represent DNS data, DJB's format for tinydns has been the most concise and
easiest to edit.  Being able to specify forward and reverse data in a single
file and keep the data in-sync so easily is a big win, as well as handling
several related zones in a single file (a win over the 'standard' zone file
format). Using any text editor to make changes is nice (a win over MS DNS and
other database backed systems), and along with that being able to easily
search for things with grep or awk or what have you (could be a win for
database backed systems, but for powerdns you need to know SQL, and for MS DNS
you need to know how to do LDAP queries and where in the tree to do them).

However, tinydns is a bit out of date. While it's file format is more flexible
than others (letting you compose literally any record using the ':' type),
several now-common records are hard to view and edit that way (such as AAA
records), and the server doesn't handle newer things like EDNS or DNSSec (or
IPv6) without patches, and some of those patches leave much to be desired.

But, a light appears with several workable options:

1. PowerDNS can read tinydns cdb files (but DNSSec support is limited; you
     have to pair with an sqlite database and can only do NSEC3+whitelies).
     Even the timestamp and location parts (for IPv4) are supported, though
     the TAI offset from UTC needs to be manually specified

2. PowerDNS can AXFR off either an actual tinydns or PowerDNS reading cdb.
     The master can be hidden locally (e.g. at 127.0.0.1 or any other `127.*`
     address). In this mode, the secondary PowerDNS stores the data in a
     database (e.g. sqlite), and can operate as a secondary DNSSec signer. It
     can then remaster for other servers. This gives full DNSSec support, but
     you lose location support (which you lose anyhow if you AXFR to other
     secondaries), and timestamp support is questionable (I haven't
     experimented with it, but I suspect replication will occur when you don't
     want it, like a few seconds before a record expires instead of a few
     seconds after its replacement appears).

So, there is a bit of compromise, but I don't tend to use the timestamp
feature (conversion to TAI format is annoying, and I prefer to be around when
a record changes anyway to clean up any fall-out), nor do I use the location
feature (I keep my different DNS views on different servers, which lessens the
likelihood of data leakage or internal compromise when externally attacked)

Since this means the tinydns format can still be useful in a modern world, I
would like to continue using the format with the more modern servers. However,
finding a patched version of tinydns-data (the program that converts your list
of DNS records into the CDB file) that does what you want can be difficult,
and tweaking the format processing code can be interesting.
Licensing is also a bit of a concern. So, I thought, why not do my own
implementation in python that isn't based on the orignal code (just the
original behaviour, and observed behaviour of some of the patched versions
when I could get my hands on them, or close enough based on their
documentation). Thus this project was born.



# File Format

The 'data' file is a simple text file.
Each line represents an intention, most of which produce one or more DNS
resource records.

* Trailing whitespace (tab, space, end-of-line) on each line is ignored.
* Emtpy lines, or lines starting with '#' or '-', are skipped (no records
    produced).
* lines are read in as a number of fields, up to NUMFIELDS = 15, where fields
    are separated by ':'
* Every record ends with a TTL (time to live), a TTD (time to die (if TTL is
    0) or start (positive ttl), and 2 character location for split-horizon.
* Unspecified fields get a default value if possible. Otherwise results in
    only some records of an intent being produced or an error. (For example,
    the '&' intent is for an NS record with an A record. If no IP address is
    given, only the NS record is produced.)
* You do not need to specify every field separator if all the trailing fields
    should be defaults.

the first character of the line denotes the type:

 % - location. Used subsequently for split-horizon stuffs.

    field 0: 2 byte location name
    field 1: IP prefix used to trigger the loc name. For example: 192.168.0 would work for 192.168.0.0/24
             can only handle /24, /16, and /8 networks.
             Parser note: each number between decimal points is parsed as an unsigned long and then truncated to 8bits, so 257 becomes 1 for example. The parser allows arbitrarily many dots, so for example '1.2.3.4.5.6.7' is valid for this field and will be put into the database, but of course, the dns server would never match it. Does offer a possibility for split horizon with ipv6, but as far as I know, no one ever did anything like that.

 Z - Complete SOA record.

    field 0: domain name
    field 1: target domain name (name of "primary" authoritative server)
    field 2: authoritative email as domain name
    field 3: serial number (omit to use datestamp of file, recommended if you are using AXFR)
    field 4: refresh time (omit to use default = 16384 == 4h 33m 4s)
    field 5: retry time (omit to use default = 2048 == 34m 8s)
    field 6: expire time (omit to use default = 1048576 == 12d 3h 16m 16s)
    field 7: min/TTL for NXDOMAIN (omit to use default 2560 == 42m 40s)
    field 8: TTL
    field 9: TTD
    field 10: Loc

 & - NS record, adds A record

    field 0: domain name
    field 1: ipv4 address, dotted decimal (omit to skip making an A record)
    field 2: target domain name. (omit to autogenerate one as ns.DOMAIN_NAME, give a name without a dot to generate name.ns.DOMAIN_NAME)
    field 3: TTL
    field 4: TTD
    field 5: Loc

 . - Simple SOA record. Same format as &. Adds an NS and A record as well

 + - A record

    field 0: domain name
    field 1: ipv4 address, dotted decimal
    field 2: TTL
    field 3: TTD
    field 4: Loc

 = - A record. Same format as +. Adds a PTR in the reverse zone as well. (in-addr.arpa)

 3 - AAAA record (enhancement by 3rd party patch, in dbndns)

    field 0: domain name
    field 1: 16 byte IPv6 address represented by 32 characters hex
    field 2: TTL
    field 3: TTD
    field 4: Loc

 6 - AAAA record, same format as 3. Adds PTR in reverse zones as well (ip6.arpa and ip6.int)

 @ - MX record. Adds A record as well

    field 0: domain name
    field 1: ipv4 address, dotted decimal (omit to skip making an A record)
    field 2: target domain name
    field 3: priority, as integer
    field 4: TTL
    field 5: TTD
    field 6: Loc

 ^ - PTR record

    field 0: domain name
    field 1: target domain name
    field 2: TTL
    field 3: TTD
    field 4: Loc

 C - CNAME record. Same format as PTR

 ' - TXT record, automatically split at 127 byte boundary

    field 0: domain name
    field 1: text data, bytes may be escaped with \ and a 3 digit octal number
    field 2: TTL
    field 3: TTD
    field 4: Loc

 : - Raw record, may not contain an AXFR, SOA, 0, NS, CNAME, PTR, nor MX record

    field 0: domain name
    field 1: record type
    field 2: data, processed like TXT (backslash escape bytes)
    field 3: TTL
    field 4: TTD
    field 5: Loc

 Addtional types from Alpine Linux's version:

 S - SRV record

    field 0: domain name
    field 1: ip
    field 2: target domain name
    field 3: port
    field 4: priority
    field 5: weight
    field 6: ttl
    field 7: ttd
    field 8: loc

 N - NAPTR

    field 0: domain name
    field 1: order
    field 2: pref
    field 3: flags
    field 4: service
    field 5: regexp
    field 6: replacement
    field 7: ttl
    field 8: ttd
    field 9: loc

 Additional types defined by us:

 c - CAA record

    field 0: domain name
    field 1: flag
    field 2: tag
    field 3: value, processed like TXT (backslash escabe bytes)
    field 4: ttl
    field 5: ttd
    field 6: loc

 t - TLSA record

    field 0: domain name
    field 1: certificate usage
    field 2: selector
    field 3: matching type
    field 4: certificate data (typically the whole cert or its hash) as hexadecimal data
    field 5: ttl
    field 6: ttd
    field 7: loc

 d - DS record

    field 0: domain name
    field 1: key tag
    field 2: algorithm
    field 3: digest type
    field 4: digest data as hexadecimal
    field 5: ttl
    field 6: ttd
    field 7: loc

 s - SSHFP record

    field 0: domain name
    field 1: algorithm
    field 2: fingerprint type
    field 3: fingerprint data as hexadecimal
    field 4: ttl
    field 5: ttd
    field 6: loc

 V - SVCB record

    field 0: domain name
    field 1: target domain name
    field 2: priority
    field 3: params, a semicolon (';') separated list of key=value pairs. Keys
	     can be text (if known by this program) or integer. The '=' may be
	     elided if there is no value for the key (value length=0) If the
	     key is given as an integer, the value is parsed as raw data in the
	     same style as text records (normal non-special characters or \ooo
	     3 digit octal sequence) where special characters include ':', '\',
	     and ';'.  Key's known by this program currently include
	     'mandatory', 'alpn', 'no-default-alpn', 'port', 'ipv4hint', and
	     'ipv6hint'.  Note that 'ech' is listed in the spec but it's
	     contents are not yet defined, so this program currently doesn't
	     accept that name.

	     - 'mandatory' takes a ',' separated list of key names or numbers.
	     - 'alpn' takes a ',' separated list of alpn-id's, using octal
	       escaping for '\', ':', ',', and ';'
	     - 'no-default-alpn' has no value
	     - 'port' takes an integer 0 to 65535
	     - 'ipv4hint' takes a regular format ipv4 address (4 dotted decimal
	       numbers)
	     - 'ipv6hint' takes an IPv6 address formatted like type '3' or '6'
	       intents.

	       TODO: RFC wireformat is space separated rather than semicolon or whatever. But it also forbids escaping in some places, which is unavoidable to our format. still, it's worth a think to see if we can support space separation to minimize conversion efforts.
	       Also, they give a format for calling out the integer value of a key, which is 'keyN' where N is an unpadded decimal integer.
    field 4: ttl
    field 5: ttd
    field 6: loc


 H - HTTPS record. Same format as SVCB See RFC9460§9 for how HTTPS records differ from generic SVCB

 / - subdelegation - modifies the way PTR records are generated for things
 like the '=' and '6' intents. This version only changes '=' (IPv4 only).
 Note: unlike other intent types, order matters for this one. All other
 intents store their affects in the database so it doesn't matter the order
 (for example, '%' intents can appear anywhere; the filtering is performed by
 the server). This intent, however, modifies the generation of the records in
 the first place. It only affects the records that come _after_ it. Note that
 this is a bit contrary to djb recommendations
 (http://cr.yp.to/djbdns/dot-arpa.html), but it does ease interoperability
 with parents or children who run other servers.

    field 0: domain name used for the base of auto-generated PTR records and
    for the optional NS record. Also can generate an A record for the NS like
    '&' records. If you are using 192.0.2.96/28, then for DeGroot format, use
    something like 'subnet96.2.0.192.in-addr.arpa'. For commonly understood
    RFC2317, use '96-111.2.0.192.in-addr.arpa'. For commonly understood
    RFC4183, use '96-28.2.0.192.in-addr.apra'. For actual RFC2317, use
    '96/28.2.0.192.in-addr.arpa'. Or anything you like, really, it doesn't
    even have to be rooted in the 'arpa' domain and it will still work, as
    covered in RFC2317.

    field 1: range. This can be specified in CIDR: 192.0.2.96/28 or as a range:
    192.0.2.96-11. Using a range is required if it isn't CIDR aligned, e.g.
    192.0.2.5-10. This range specifies which auto-generated PTR records to
    modify, and which CNAME records to generate for a parent zone.

    field 2: target domain name for NS record. Leave blank to omit the NS
    record and omit CNAME records. Set to '.' to omit the NS record but
    include the CNAME records. Set to the actual delagation name server to get
    NS record and CNAME records. If you truly want to delegate to '.', use an
    additional '&' record.

    field 3: IPv4 address of the NS server. leaving blank omits the A record
    (just like the '&' intent). This field is ignored if field 2 is empty or '.'

    field 4: TTL
    field 5: TTD
    field 6: Loc

 
To do fancy things like hidden primary but still report the primary, use a Z record for the SOA, then & records for the NS that are "visible" (not hidden). Even though & is usually for delegation, it isn't when there is an SOA.

A fun excersize: What to do if a subdomain is a zone (that is, it has an SOA). Does the parent and subdomain both share the same NS records?

Note: If you use specify the same name in multiple ways, you can get multiple
records. E.g. a '.' record with an IP address, then an '=' record for the name
server with the same IP address (useful to get the rDNS PTR record that isn't
included with the '.' intent) will give you two A records for the same name
with the same value. I recommend omitting the IP for the '.' intent and having
it in the '=' intent to reduce confusion. The feature of having multiple
records for one name can be used in DNS lead unbalanced load balancing.

