#!/usr/bin/env python3
"""
FB Study Guide — an interactive study app for networking, SAN, NAS and Linux.

Single file. Standard library only (tkinter). Run with:
    python3 fb_study_guide.py

Modes: Browse, Cards, Quiz, Search.
Progress is saved to ~/.fb_study_guide.json
"""

import hashlib
import http.server
import json
import math
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

try:
    import tkinter as tk
    import tkinter.font as tkfont
    HAVE_TK = True
except Exception:            # Tk is optional; only the --tk fallback needs it
    HAVE_TK = False

    class _NoTk:
        """Stand-in so the Tkinter classes can still be defined without Tk."""

        def __init__(self, *a, **k):
            raise RuntimeError("Tkinter is not available in this Python build.")

    class _NoTkModule:
        def __getattr__(self, name):
            return _NoTk

    tk = tkfont = _NoTkModule()

APP_TITLE = "FB Study Guide"
PROGRESS_PATH = os.path.join(os.path.expanduser("~"), ".fb_study_guide.json")


# ----------------------------------------------------------------------------
# Content
# ----------------------------------------------------------------------------
# Each topic: id, cat, title, q (question form), a (answer, light markup).
# Markup: "## " subhead, "- " bullet, ``` fenced code, **bold**, `inline code`.

TOPICS = [

# === Networking Fundamentals ================================================
dict(id="icmp", cat="Networking Fundamentals", title="ICMP",
     q="What is ICMP and what is it used for?",
     a="""**ICMP** is the Internet Control Message Protocol. It is a Layer 3 protocol
(IP protocol number 1) used for control and error signalling — it does not carry
application data and has no port numbers.

## Common message types
- Echo Request (8) / Echo Reply (0) — used by `ping`
- Destination Unreachable (3) — host, network, port, or protocol unreachable
- Time Exceeded (11) — TTL hit zero; this is what makes `traceroute` work
- Redirect (5) — a router telling a host about a better next hop

## Why it matters in support
ICMP is frequently rate-limited or blocked by firewalls, so **a failed ping does
not prove a host is down**. Test the actual service port instead.

Path MTU Discovery relies on ICMP type 3 code 4 (Fragmentation Needed). If ICMP
is blocked, PMTUD breaks and you get a black hole: small packets succeed, large
transfers hang. This is the classic jumbo-frame failure signature.

```
ping -c 4 10.0.5.20
ping -M do -s 8972 10.0.5.20     # unfragmentable 9000-byte test
```"""),

dict(id="ping", cat="Networking Fundamentals", title="Ping",
     q="What is ping and what does it actually tell you?",
     a="""**Ping** tests reachability and round-trip latency by sending ICMP Echo
Requests and waiting for Echo Replies. It reports RTT (min/avg/max/stddev) and
packet loss percentage.

## Commands
```
ping -c 5 10.0.5.20              # Linux, 5 packets
ping -i 0.2 -c 100 10.0.5.20     # faster interval, loss testing
ping -s 1472 10.0.5.20           # specific payload size
ping -M do -s 8972 10.0.5.20     # don't fragment — MTU testing

ping -n 5 10.0.5.20              # Windows
ping -f -l 8972 10.0.5.20        # Windows, don't fragment
```

## Reading the result
- **Loss with high variance** — congestion or a flapping link
- **Consistent high RTT** — routing path or physical distance
- **No reply at all** — could be down, could be ICMP filtered

Ping proves L3 reachability only. A host can answer ping while the service you
care about is dead. Follow up with `nc -zv host port`."""),

dict(id="traceroute", cat="Networking Fundamentals", title="Traceroute",
     q="How does traceroute work, and how do you read its output?",
     a="""**Traceroute** maps the hop-by-hop path to a destination by sending packets
with an incrementing TTL. Each router that decrements the TTL to zero discards
the packet and returns an **ICMP Time Exceeded**, which reveals that router's
address. The final host returns Port Unreachable (UDP mode) or Echo Reply (ICMP
mode). Three probes per hop give you three RTT samples.

## Commands
```
traceroute 10.0.5.20             # Linux, UDP high ports by default
traceroute -I 10.0.5.20          # ICMP mode
traceroute -T -p 445 10.0.5.20   # TCP mode — best through firewalls
tracert 10.0.5.20                # Windows (ICMP)
```

## Reading it correctly
- `* * *` means **that hop did not reply** — not that traffic stopped. Many
  routers deprioritize or suppress ICMP responses.
- An RTT spike at hop 4 that returns to normal at hops 5–10 is a control-plane
  artifact, not real latency. Only the **final hop** RTT reflects end-to-end.
- The forward path shown may not match the return path.

For intermittent problems, use `mtr` instead — a single traceroute is a snapshot."""),

dict(id="mtr", cat="Networking Fundamentals", title="MTR",
     q="What is mtr and when would you use it over traceroute?",
     a="""**mtr** (My Traceroute) combines traceroute's path discovery with continuous
ping, producing a live table of per-hop loss percentage and latency over time.

Use it whenever the problem is **intermittent** — a single traceroute run is one
sample and will miss packet loss that occurs 5% of the time.

```
mtr 10.0.5.20                    # interactive
mtr -rwc 100 10.0.5.20           # report mode, wide, 100 cycles
mtr -T -P 445 10.0.5.20          # TCP probes to a real service port
mtr -n 10.0.5.20                 # skip DNS resolution
```

## Reading it
Loss shown at an intermediate hop that **does not persist to the final hop** is
almost always ICMP rate-limiting on that router, not real loss. Only loss that
continues through to the last hop is real. This single point trips up most
people reading mtr output."""),

dict(id="netstat", cat="Networking Fundamentals", title="netstat",
     q="What does netstat show, and what has replaced it?",
     a="""**netstat** displays network connections, routing tables, interface
statistics, and per-protocol counters. On modern Linux it is deprecated (part of
the legacy `net-tools` package, often not installed) — `ss` is the replacement.

```
netstat -tulpn     # TCP/UDP listening sockets with owning process
netstat -an        # all sockets, numeric
netstat -rn        # routing table
netstat -i         # interface stats (errors, drops)
netstat -s         # per-protocol statistics

netstat -ano       # Windows, with PID
netstat -anob      # Windows, with owning executable
```

Important: netstat shows sockets on the **local** machine. To check whether a
port is open on a **remote** machine, use `nmap` or `nc -zv`."""),

dict(id="tcpudp", cat="Networking Fundamentals", title="TCP vs UDP",
     q="What are TCP and UDP used for, and what are the differences?",
     a="""Both are Layer 4 transport protocols. The difference is what guarantees they
provide.

## TCP — Transmission Control Protocol
Connection-oriented and reliable. Establishes a connection with a **three-way
handshake** (SYN → SYN-ACK → ACK), then provides:
- Sequence numbers and acknowledgements
- Retransmission of lost segments
- In-order delivery
- Flow control (receive window)
- Congestion control
Teardown is FIN / FIN-ACK, or an abrupt RST. Header is 20 bytes minimum.

Used by: HTTP/HTTPS, SSH, SMB, iSCSI, FTP, and **all modern NFS**.

## UDP — User Datagram Protocol
Connectionless and best-effort. 8-byte header, no handshake, no retransmission,
no ordering. If the application needs reliability it must implement it itself.

Used by: DNS, DHCP, syslog, SNMP, NTP, VoIP/RTP, video streaming, gaming.

## The storage-relevant nuance
Gaming is one use of UDP, but the point that matters here is **NFS**: NFSv3 could
run over UDP, and occasionally still is on legacy systems, but virtually all
modern deployments use TCP. **NFSv4 requires TCP.** UDP-mounted NFS behaves badly
on a lossy network because there is no retransmission logic — a strong reason to
check `nfsstat -m` for `proto=udp` when troubleshooting old mounts."""),

dict(id="ports", cat="Networking Fundamentals", title="Common ports",
     q="What are the commonly used ports and what runs on them?",
     a="""## The ones from your notes
- **21** FTP control (20 is FTP data in active mode)
- **22** SSH — also SCP and SFTP
- **80** HTTP
- **443** HTTPS
- **514** Syslog (UDP)
- **636** **LDAPS** — LDAP over SSL/TLS

**Correction:** 636 is LDAPS, not LDAP. Plain LDAP is **389**. This distinction
comes up constantly in AD and directory troubleshooting.

## Others worth knowing in this role
- **53** DNS — UDP for queries, TCP for zone transfers and large responses
- **88** Kerberos
- **111** rpcbind / portmapper (NFSv3)
- **123** NTP
- **135 / 139** MS RPC endpoint mapper / NetBIOS session
- **161 / 162** SNMP agent / SNMP trap
- **389** LDAP (and StartTLS)
- **445** SMB over TCP
- **2049** NFS
- **3260** iSCSI
- **3389** RDP
- **8080 / 8443** common alternate HTTP/HTTPS

```
nc -zv 10.0.5.20 2049
nmap -p 22,445,2049,3260 10.0.5.20
```"""),

dict(id="subnetting", cat="Networking Fundamentals", title="Subnetting",
     q="What is subnetting and why is it done?",
     a="""**Subnetting** divides an IP network into smaller networks using the subnet
mask (or CIDR prefix length) to borrow bits from the host portion of the address.

## Why
- Smaller broadcast domains — less broadcast noise per segment
- Routing efficiency and route summarization
- Security and policy segmentation (separate storage, management, VM traffic)
- Address conservation

## Quick math
A /24 is 256 addresses, 254 usable. Every bit you add halves the block:
- /25 = 128 · /26 = 64 · /27 = 32 · /28 = 16 · /29 = 8 · /30 = 4 (2 usable)
- /31 = 2, valid for point-to-point links per RFC 3021

Example — `10.0.5.0/26`: range .0–.63, network .0, broadcast .63, usable .1–.62.

```
ipcalc 10.0.5.0/26
sipcalc 10.0.5.0/26
ip route get 10.0.9.7            # which interface/gateway would be used
```

## Storage relevance
Host initiators and array data VIFs must either share a subnet or have working
routing between them. A mismatched mask (/24 configured on the array, /25 on the
host) produces the classic "half the hosts can mount and half cannot" symptom."""),

dict(id="arp", cat="Networking Fundamentals", title="ARP",
     q="What is ARP and why does gratuitous ARP matter for storage?",
     a="""**ARP** (Address Resolution Protocol) maps an IPv4 address to a MAC address
within a single broadcast domain. A host broadcasts "who has 10.0.5.20", the
owner replies by unicast with its MAC, and the result is cached in the ARP table
with a timeout. IPv6 uses NDP instead.

```
ip neigh show                    # modern Linux
ip neigh flush all
arp -an                          # legacy
arp -a                           # Windows
arp -d *                         # Windows, clear cache
```

## Gratuitous ARP — the part that matters
A **gratuitous ARP** is an unsolicited ARP announcing an IP-to-MAC binding.
When an array VIP fails over from one controller or blade to another, the new
owner sends gratuitous ARP so switches and hosts update their tables immediately.

If gratuitous ARP is filtered or the host has a long ARP cache timeout, clients
keep sending frames to the **old** MAC after a failover — traffic black-holes
until the cache expires. That is a real, seen-in-the-field failure mode, and
`ip neigh show` on the client is how you confirm it."""),

dict(id="gateway", cat="Networking Fundamentals", title="Gateway",
     q="What is a gateway?",
     a="""A **default gateway** is the router address a host sends traffic to when the
destination is not on its own subnet. The host consults its routing table; if no
specific route matches, the packet goes to the default gateway.

```
ip route show
ip route get 8.8.8.8             # shows the exact decision
route print                      # Windows
```

**Correction to your note:** a default gateway *routes* between networks — it
forwards packets based on destination IP and rewrites the L2 header. It does not
translate protocols. A **protocol gateway** is a different, more specialised
device that converts between dissimilar protocols (for example an FC-to-iSCSI
bridge, or a legacy voice gateway). Conflating the two is a common interview slip.

Missing or wrong default gateway is a classic cause of "I can reach hosts on my
own subnet but nothing else.\""""),

# === Switching and Layer 2/3 ================================================
dict(id="l2l3", cat="Switching & Layer 2/3", title="Layer 2 vs Layer 3 switches",
     q="What is the difference between a Layer 2 and a Layer 3 switch?",
     a="""## Layer 2 switch
Operates at the Data Link layer. Forwards **frames** based on destination **MAC
address**. It builds a MAC address table by learning the source MAC of every
frame it receives and noting the port. Unknown-unicast and broadcast frames are
flooded to all ports in the VLAN. Each VLAN is one broadcast domain.

## Layer 3 switch
Does everything a Layer 2 switch does, **plus** routes IP packets between VLANs
and subnets. It maintains a routing table and ARP table, supports SVIs (switched
virtual interfaces), and performs routing in hardware ASICs rather than in
software — which is what distinguishes it from a traditional router.

## The distinction to state cleanly
- L2: **frames**, MAC addresses, one broadcast domain per VLAN, no routing
- L3: **packets**, IP addresses, inter-VLAN routing, routing table

**Terminology correction:** at Layer 2 the unit is a *frame*. A *packet* is the
Layer 3 unit that sits inside the frame's payload. Saying "L2 forwards packets
based on MAC" mixes the layers, and interviewers listen for it."""),

dict(id="mlag", cat="Switching & Layer 2/3", title="MLAG and vPC",
     q="What are MLAG and vPC, and why are they used?",
     a="""## Link aggregation first
LACP (802.3ad) bundles multiple physical links into one logical link for
bandwidth and redundancy. Standard LAG requires **both ends on the same switch**
— so the switch itself becomes a single point of failure.

## MLAG
**Multi-Chassis Link Aggregation** lets two physical switches present themselves
as a single logical LAG peer. A host or array can then dual-home to two separate
switches while running one port-channel, giving both switch-level redundancy and
active/active bandwidth — no spanning-tree blocked links.

## vPC
**Virtual Port Channel** is Cisco Nexus's implementation of MLAG. Other vendors:
Arista calls it MLAG, Juniper MC-LAG, Dell VLT. On Nexus it needs a **peer-link**,
a **peer-keepalive link**, and a matching **vPC domain ID** on both switches.
Configuration must be consistent between peers or the consistency check fails and
ports are suspended.

## Two things to keep straight
- Your note said a FlashBlade connects to two switches as one logical
  port-channel — that is correct, and it is why VIP failover and link loss are
  non-disruptive.
- **"VPC" also means Virtual Private Cloud** in AWS/GCP contexts. Completely
  unrelated. Clarify which one is being asked about."""),

dict(id="jumbo", cat="Switching & Layer 2/3", title="Jumbo frames",
     q="What are 9000 MTU jumbo frames and what breaks when they are misconfigured?",
     a="""Standard Ethernet carries a 1500-byte payload (MTU). **Jumbo frames** raise
that, commonly to **9000**.

## The actual benefit
Fewer frames to move the same data means less per-packet header overhead, fewer
interrupts, and less CPU per gigabyte transferred. That matters for **large
sequential I/O** — NFS, iSCSI, backups, replication.

**Correction to your note:** it is not about "certain types of files." It is
about I/O size and per-packet overhead. A workload of 4K random reads sees almost
no benefit from jumbo frames.

## The critical rule
MTU must match **end to end**: host NIC, every switch port, every inter-switch
link, any router interface, and the array data ports. One device left at 1500
causes fragmentation — or, if the Don't Fragment bit is set and ICMP is filtered,
a **silent black hole**.

That black hole has a signature you should recognise immediately: *ping works,
the mount succeeds, small operations succeed, and large transfers hang.*

## Terminology
NIC MTU 9000 refers to payload. Switches count the whole frame including headers,
so they are typically configured to 9216 for headroom.

## Test it
```
ping -M do -s 8972 10.0.5.20     # Linux: 8972 + 8 ICMP + 20 IP = 9000
ping -f -l 8972 10.0.5.20        # Windows
ip link set eth0 mtu 9000
ip link show eth0                # verify
```
If 1472 succeeds and 8972 fails, you have a jumbo mismatch in the path."""),

# === DNS ====================================================================
dict(id="dns", cat="DNS & Name Resolution", title="DNS",
     q="What is DNS?",
     a="""**DNS** is the Domain Name System — a distributed, hierarchical database that
resolves human-readable names to IP addresses and other record types. Port **53**,
UDP for standard queries, TCP for zone transfers and responses too large for a
single datagram.

## Resolution path
Stub resolver on the client → recursive resolver → root servers → TLD servers →
authoritative servers → answer. Results are cached at each layer for the duration
of the record's TTL.

**Correction to your note:** what you described is **Dynamic DNS (DDNS)** — the
mechanism by which a client or DHCP server automatically updates its A and PTR
records when its address changes. DDNS is one feature; DNS is the whole system.
The core purpose of DNS is name-to-address resolution and providing a stable,
memorable name that is independent of the underlying IP.

## Why it matters here
NFS exports, SMB shares, and Kerberos all depend on **both forward and reverse**
DNS being correct and consistent. Kerberos in particular fails when the PTR does
not match the name in the SPN. A large share of "slow mount" and "authentication
fails intermittently" cases are DNS."""),

dict(id="arecord", cat="DNS & Name Resolution", title="A record",
     q="What is an A record and why is it used?",
     a="""An **A record** maps a hostname to an **IPv4 address**. The IPv6 equivalent is
an **AAAA record**. This is the record used for every ordinary forward lookup —
when a client resolves `fb01.corp.local` to `10.0.5.20`, it is reading an A record.

```
dig +short fb01.corp.local A
dig fb01.corp.local            # full response with TTL and flags
nslookup fb01.corp.local
```

## Round-robin
Multiple A records can exist for the same name. The resolver returns them in
rotating order, spreading clients across addresses. This is how array data VIPs
are commonly published so NFS clients distribute across data interfaces — cheap
load distribution with no load balancer.

Caveat: it is distribution, not balancing. There is no health checking, so a
down VIP still gets handed out until the record is removed. Client-side caching
also skews the spread.

## A vs CNAME
An A record points to an address. A **CNAME** points to another *name*, which
must then be resolved. A CNAME cannot coexist with other records at the same
name, and Kerberos SPN lookups against a CNAME are a frequent source of
authentication failures."""),

dict(id="ptrrecord", cat="DNS & Name Resolution", title="PTR record",
     q="What is a PTR record?",
     a="""A **PTR record** is reverse DNS — it maps an IP address back to a hostname.
Records live in the `in-addr.arpa` zone (`ip6.arpa` for IPv6) with the octets
reversed: `10.0.5.20` becomes `20.5.0.10.in-addr.arpa`.

```
dig -x 10.0.5.20
nslookup 10.0.5.20
host 10.0.5.20
```

## Why it matters far more than people expect
- **NFS**: server-side export checks and logging resolve client IPs. A missing
  PTR makes the server wait on a lookup that must time out first — the client
  sees a mount that takes 30+ seconds or hangs.
- **Kerberos / SMB**: the client may canonicalize the name it connects to via
  reverse lookup. If the PTR disagrees with the SPN, Kerberos fails and the
  client silently falls back to NTLM, or fails outright.
- **Logs**: without PTR, every log line shows a raw IP.

Forward and reverse must **agree**. `dig +short name` and `dig -x <that address>`
should round-trip back to the same name. Checking that round trip is one of the
fastest high-value checks in a NAS authentication case."""),

dict(id="records", cat="DNS & Name Resolution", title="Other record types",
     q="What other DNS record types should you know?",
     a="""- **CNAME** — alias pointing to another name. Cannot coexist with other
  records at the same name. Watch it with Kerberos.
- **MX** — mail exchanger, with priority values.
- **NS** — delegates a zone to authoritative name servers.
- **SOA** — start of authority: primary server, admin contact, serial number,
  refresh/retry/expire, and the negative-caching TTL. The serial is how you tell
  whether a zone change actually replicated.
- **TXT** — arbitrary text; used for SPF, DKIM, and domain verification.
- **SRV** — service location: `_service._proto.name` with priority, weight, port,
  and target. **Active Directory depends on these heavily** — clients find domain
  controllers and KDCs through SRV records.

```
dig NS corp.local
dig SRV _kerberos._tcp.corp.local
dig SRV _ldap._tcp.dc._msdcs.corp.local
dig SOA corp.local
```
If AD clients cannot find a DC, broken or missing SRV records are the first thing
to check."""),

dict(id="dig", cat="DNS & Name Resolution", title="dig",
     q="What is dig and how do you use it to troubleshoot?",
     a="""**dig** (Domain Information Groper) is a DNS query tool. It is preferred over
`nslookup` because its output is unambiguous — it shows the full response,
including flags, TTLs, and which server answered — whereas nslookup can silently
mislead you about whether an answer was authoritative or cached.

```
dig fb01.corp.local                    # full response
dig +short fb01.corp.local             # just the answer
dig @10.0.0.53 fb01.corp.local         # query a specific server
dig -x 10.0.5.20                       # reverse lookup
dig +trace fb01.corp.local             # walk from the root — finds delegation breaks
dig +noall +answer fb01.corp.local     # answer section only
dig NS corp.local
dig SRV _kerberos._tcp.corp.local
dig +tcp fb01.corp.local               # force TCP
```

## Read the header, not just the answer
- `status: NOERROR` — resolved. `NXDOMAIN` — name does not exist.
  **`SERVFAIL`** — the server tried and failed: broken delegation, DNSSEC
  failure, or an unreachable upstream. Very different from NXDOMAIN.
- `flags: aa` — authoritative answer, straight from the zone's own server.
- `flags: ra` — recursion available.
- The TTL in the answer tells you how long it will stay cached — useful when
  someone "fixed" a record and it has not taken effect yet.

`+trace` is the single most valuable option when resolution works from one
server but not another."""),

# === SNMP ===================================================================
dict(id="snmp", cat="Monitoring & Management", title="SNMP",
     q="What is SNMP and how does it work?",
     a="""**SNMP** (Simple Network Management Protocol) is a standard protocol for
monitoring and managing network devices — routers, switches, servers, storage
arrays — over IP.

## Model
An **agent** runs on the managed device and exposes a tree of values identified by
**OIDs** (object identifiers), whose structure and meaning are defined by **MIBs**.
A **manager** (monitoring system) polls the agent with GET, GETNEXT, or GETBULK,
and can change values with SET. The agent can also push unsolicited **TRAP** or
**INFORM** messages when an event occurs — INFORM is acknowledged, TRAP is not.

Ports: **161/UDP** for the agent, **162/UDP** for traps.

## Versions
- **v1** — original, plaintext community strings, limited error handling
- **v2c** — adds GETBULK and better errors, still plaintext community strings
- **v3** — adds authentication (MD5/SHA) and encryption (DES/AES) with
  user-based security. Use v3 in production.

```
snmpwalk -v2c -c public 10.0.5.20 .1.3.6.1.2.1.1
snmpget -v2c -c public 10.0.5.20 sysUpTime.0
snmpwalk -v3 -l authPriv -u monuser -a SHA -A authpass \\
         -x AES -X privpass 10.0.5.20 system
```

## In storage support
Arrays expose hardware health, capacity, and alert state via SNMP and send traps
to the monitoring platform. A wrong community string, a v2c/v3 mismatch, or
blocked UDP 162 means **alerts silently stop arriving** — the array is fine, the
monitoring is blind, and nobody notices until something breaks."""),

# === OSI ====================================================================
dict(id="osi", cat="OSI Model", title="The OSI model",
     q="What is the OSI model and what are its seven layers?",
     a="""The **OSI model** is a seven-layer conceptual reference model describing how
data moves through a network stack. Each layer provides services to the layer
above and consumes services from the layer below. Data is encapsulated on the way
down and decapsulated on the way up.

It is a **teaching and troubleshooting framework**, not an implementation — what
is actually implemented is the TCP/IP model (Link, Internet, Transport,
Application).

## The layers, bottom to top
**1 — Physical.** Bits on the wire. Cables, connectors, optics, voltage,
pinouts, signalling. PDU: *bits*. Check: link lights, SFP seating, fiber
cleanliness, `ethtool eth0`.

**2 — Data Link.** Node-to-node delivery within a segment. MAC addressing,
framing, FCS error detection, VLAN tagging (802.1Q), LACP, spanning tree.
PDU: *frame*. Devices: switches, NICs, bridges.

**3 — Network.** Logical addressing and routing between networks. IP, ICMP,
OSPF, BGP; ARP sits between 2 and 3. PDU: *packet*. Devices: routers, L3 switches.
**The layer is called "Network," not "Networking."**

**4 — Transport.** End-to-end delivery, segmentation and reassembly, port
numbers. TCP gives reliability, ordering, flow control, and congestion control;
UDP gives none of it. PDU: *segment* (TCP) / *datagram* (UDP).

**5 — Session.** Establishing, managing, and terminating sessions between
applications. RPC, NetBIOS session service, SMB session setup.

**6 — Presentation.** Data representation: character encoding, serialization
(**XDR**, which NFS uses), compression. TLS is commonly placed here.

**7 — Application.** The protocols applications speak: HTTP, NFS, SMB, FTP, DNS,
SMTP, S3.

Mnemonic bottom-up: *Please Do Not Throw Sausage Pizza Away.*

## Why it is actually useful
Troubleshoot **bottom-up**. Link down (L1) → wrong VLAN or MTU mismatch (L2) →
wrong subnet, mask, or gateway (L3) → firewall blocking the port (L4) → protocol
version or authentication mismatch (L5–L7). Naming the layer you have proven good
is how you narrow a problem fast and hand off cleanly."""),

# === SAN ====================================================================
dict(id="sancomponents", cat="SAN & Fibre Channel", title="SAN components",
     q="What components make up a SAN?",
     a="""## Host
The server that needs block storage. It runs a multipath layer — Linux
device-mapper-multipath, Windows MPIO, or ESXi NMP/HPP — to coalesce the multiple
paths to a volume into a single usable device.

## HBA — Host Bus Adapter
The Fibre Channel adapter card in the host (typically QLogic or Emulex). It
offloads the FC protocol stack from the CPU. Each **port** on the HBA has its own
WWPN. On Linux they appear under `/sys/class/fc_host/hostN/`. The iSCSI
equivalent is a standard NIC, or a CNA/iSCSI HBA for offload.

## SFP — Small Form-factor Pluggable
Pluggable optical transceiver that converts electrical signals to optical and
back. Required on **both** the device side and the switch side. Must match on
speed (8/16/32/64G), wavelength, and fiber type (OM3/OM4 multimode short-wave, or
single-mode long-wave). **Dirty or mismatched optics are a leading cause of CRC
errors and link flapping** — check with `show interface transceiver`.

## Switch — the fabric
Brocade or Cisco MDS. Forwards frames using FCIDs, runs the fabric services
including the **name server**, and enforces **zoning**. Standard practice is two
completely independent fabrics (Fabric A and Fabric B) — never merged, so a
fabric-wide event cannot take out both paths.

## Storage array
FlashArray, FlashBlade, or any array presenting volumes. Each FC port has a WWPN
and registers with the fabric name server on login (FLOGI/PLOGI).

**Correction to your note:** a home computer or laptop is not a SAN storage
device in any meaningful sense. A SAN target is a purpose-built array — or a host
explicitly configured with FC/iSCSI *target* software. The distinction matters
because SAN implies block protocol, fabric services, and multipathing.

## Also components in practice
The cabling and patch panels, and the host-side multipath software — both are
where a surprising number of SAN cases actually land."""),

dict(id="lun", cat="SAN & Fibre Channel", title="Creating a LUN",
     q="What does it mean to create a LUN?",
     a="""**LUN** = Logical Unit Number — the identifier a SCSI target uses to expose a
logical unit to an initiator. Colloquially "the LUN" means the volume itself.

## The flow end to end
1. Create the **volume** on the array.
2. **Connect** it to a host or host group — the array assigns a LUN ID (e.g. 1).
3. Zoning must already permit the initiator WWPN to see the target WWPN.
4. The host **rescans** its SCSI buses.
5. The host discovers one SCSI device **per path** (4 paths = 4 block devices).
6. **Multipath** coalesces those into a single device.
7. Partition, create a filesystem or add to LVM, mount.

```
rescan-scsi-bus.sh                          # Linux
echo "- - -" > /sys/class/scsi_host/host0/scan
lsscsi
multipath -ll
lsblk

diskpart  →  rescan                         # Windows
```
On ESXi: Storage Adapters → Rescan Storage.

## Gotchas
- LUN IDs should be **consistent across all paths** for a given host.
- Some HBAs stop probing if LUN 0 does not exist.
- If the host sees the device on only some paths, the problem is zoning or a
  dead port, not the array.
- Seeing 4 devices and no multipath device means multipathd is not running or
  the WWID is not matching."""),

dict(id="lunmasking", cat="SAN & Fibre Channel", title="LUN masking",
     q="What is LUN masking, and how does it differ from zoning?",
     a="""**LUN masking** is an authorization mechanism that controls which hosts can see
and access specific LUNs. It is enforced at the **array** (target side), by
binding volumes to a host object that is defined by that host's WWPNs or IQNs.

## Zoning vs masking — say this cleanly
- **Zoning** is enforced in the **fabric**. It controls which devices can *talk
  to* each other at all.
- **Masking** is enforced on the **array**. It controls which LUNs a given
  initiator can *see* once it can talk.

You need both. Zoning without masking means every zoned host sees every LUN on
that array — which is exactly how two unrelated hosts end up writing to the same
volume and corrupting the filesystem. That is the reason masking exists.

Practical check when a host cannot see a volume: confirm the initiator logged
into the fabric (`show flogi database`), confirm zoning includes both WWPNs,
then confirm the volume is connected to the right host object on the array. In
that order — it follows the path."""),

dict(id="zoning", cat="SAN & Fibre Channel", title="Hard vs soft zoning",
     q="What is hard zoning and what is soft zoning?",
     a="""## Soft zoning
Enforced by the fabric **name server**. When an initiator queries the name server
asking what devices exist, it is only told about devices in its own zone. But if
a device already knows — or guesses — a destination FCID, frames will still be
forwarded. It is **visibility control, not enforcement**.

## Hard zoning
Enforced in the switch **ASIC on a frame-by-frame basis**. Frames destined for a
device outside the zone are dropped in hardware regardless of what the sender
knows. This is **true enforcement**.

## The trap to avoid
People routinely equate *hard zoning = port zoning* and *soft zoning = WWN
zoning*. **That is not the definition.** Those are two independent axes:
- **Membership** can be defined by port (Domain,Index) or by WWPN.
- **Enforcement** is hard or soft.

Modern Brocade and Cisco switches enforce **WWPN zoning in hardware** — so you
routinely get WWPN membership *and* hard enforcement together. Knowing this
distinction is a reliable way to demonstrate real fabric knowledge.

## Best practice
**Single-initiator / single-target zoning** — one initiator WWPN and one target
WWPN per zone. This minimises RSCN (Registered State Change Notification) storms:
when a device leaves or joins, only genuinely affected devices are notified,
instead of every member of a large zone getting disrupted.

```
# Brocade
zonecreate "z_host1_fb01_p0", "10:00:...;52:4a:..."
cfgadd "prod_cfg", "z_host1_fb01_p0"
cfgenable "prod_cfg"
zoneshow ; nsshow ; switchshow

# Cisco MDS
zone name z_host1_fb01_p0 vsan 10
zoneset activate name prod_zs vsan 10
show zoneset active ; show flogi database ; show fcns database
```"""),

dict(id="wwn", cat="SAN & Fibre Channel", title="WWPN and WWNN",
     q="What is a WWPN and what is a WWNN?",
     a="""Both are **64-bit (8-byte) globally unique identifiers** assigned from IEEE OUI
space, written as colon-separated hex: `10:00:00:90:fa:12:34:56`.

- **WWNN** — World Wide **Node** Name. Identifies the *device or node* as a whole:
  an entire HBA card, or an entire array.
- **WWPN** — World Wide **Port** Name. Identifies a *single port*. One node has
  multiple ports, so **one WWNN maps to several WWPNs**.

## The point that matters
**Zoning and LUN masking are done by WWPN, not WWNN.** This trips people up
constantly — zoning by node name would expose every port on the device.

## Finding them
```
cat /sys/class/fc_host/host*/port_name      # Linux WWPN
cat /sys/class/fc_host/host*/node_name      # Linux WWNN
systool -c fc_host -v

Get-InitiatorPort                           # Windows

show flogi database                         # Cisco MDS — who logged in
show fcns database
switchshow ; nsshow                         # Brocade
```
ESXi: Configure → Storage Adapters shows both per HBA.

## iSCSI equivalent
The **IQN** — `iqn.1994-05.com.redhat:host1abc`. Same role: it is the identifier
you zone (well, mask) against."""),

# === File protocols =========================================================
dict(id="nfssmb", cat="File Protocols", title="NFS vs SMB",
     q="What are NFS and SMB, and what are the differences?",
     a="""## NFS — Network File System
Native to Unix/Linux.
- **v3** is effectively stateless, with locking handled by separate side
  protocols (NLM/NSM). It depends on **rpcbind (111)**, mountd, and statd, which
  use dynamic ports — hence its reputation for being painful through firewalls.
- **v4** is stateful, runs entirely over **port 2049**, integrates locking, ACLs,
  and delegations, supports Kerberos (`krb5`, `krb5i`, `krb5p`), and uses
  `name@domain` identity mapping rather than raw UID/GID on the wire.
- **v4.1** adds sessions and pNFS; **v4.2** adds server-side copy.

## SMB — Server Message Block
Native to Windows. Stateful, uses **TCP 445** (139 for legacy NetBIOS).
- **SMB1** — deprecated and insecure. Do not use it.
- **SMB2** — dramatically less chatty than SMB1.
- **SMB3** — encryption, multichannel, RDMA (SMB Direct), persistent handles.
Integrates natively with AD, Kerberos, and NTFS-style ACLs.

## Differences that actually cause cases
- **Identity model** — NFS thinks in UID/GID and POSIX permissions; SMB thinks in
  SIDs and NTFS ACLs.
- **Case sensitivity** — NFS is case-sensitive; SMB is case-insensitive but
  case-preserving.
- **Locking semantics** differ, which matters for applications shared between
  both.
- **Failover behaviour** — SMB3 persistent handles survive some interruptions;
  NFS `hard` mounts retry indefinitely.

## Multiprotocol
Exporting the same dataset over both requires a deliberate identity-mapping
strategy and a chosen ACL model. Without one, you get permissions that look
correct on one protocol and deny access on the other — a very common escalation."""),

dict(id="nfsmount", cat="File Protocols", title="Mounting NFS",
     q="How do you mount an NFS share on a Unix system?",
     a="""```
sudo mount -t nfs 192.168.1.100:/volume1/data /mnt/nfs_share
```
With options that you would actually use in production:
```
sudo mount -t nfs -o vers=4.1,hard,timeo=600,retrans=2,\\
rsize=1048576,wsize=1048576 10.0.5.20:/data /mnt/data
```
Persistent, in `/etc/fstab`:
```
10.0.5.20:/data  /mnt/data  nfs  vers=4.1,hard,_netdev  0 0
```

## Verify and inspect
```
mount | grep nfs
nfsstat -m                       # shows the options actually negotiated
findmnt -t nfs,nfs4
showmount -e 10.0.5.20           # list exports (v3)
umount -f /mnt/data ; umount -l /mnt/data
```

## The options that matter
- **`hard`** — retry indefinitely on server timeout. Correct for real data.
  **`soft`** returns an I/O error instead, which applications frequently ignore,
  risking silent corruption. Use soft only for read-only or scratch data.
- **`vers=`** — pin it. Auto-negotiation landing on v3 when you expected v4.1
  explains a lot of odd behaviour.
- **`rsize`/`wsize`** — check with `nfsstat -m` that you got what you asked for.
- **`noac`/`actimeo=0`** — disable attribute caching; correctness over speed.
- **`sec=krb5p`** — Kerberos with encryption.
- `intr` is a no-op on modern kernels.

## Troubleshooting order
ping → `nc -zv server 2049` (and `rpcinfo -p server` for v3) → `showmount -e` →
check the export rule and squashing → **check forward *and* reverse DNS**."""),

dict(id="rpc", cat="File Protocols", title="RPC",
     q="What is RPC and how does NFS use it?",
     a="""**RPC** (Remote Procedure Call) is the mechanism that lets a client invoke a
procedure on a remote server as though it were running locally. NFS is built on
**ONC RPC** (Sun RPC), with **XDR** (External Data Representation) handling
platform-neutral encoding of arguments and results — which is why NFS works
between machines with different byte orders and word sizes.

## NFSv3 and rpcbind
v3 registers its services with **rpcbind/portmapper on port 111**. A client asks
rpcbind which port `mountd`, `statd`, and `nlockmgr` are listening on, because
those use **dynamic** ports. This is exactly why NFSv3 through a firewall is
painful, and why you pin those ports in `/etc/nfs.conf` when you must.

```
rpcinfo -p 10.0.5.20          # list registered programs and ports
rpcinfo -T tcp 10.0.5.20 nfs
```

## NFSv4 dropped it
Everything runs over **2049**. No rpcbind, no dynamic ports, no separate lock
manager. One firewall rule. This alone is a strong argument for v4 in any
firewalled environment.

In a packet capture you will see NFS operations framed as RPC **Call** and
**Reply** pairs — Wireshark matches them and gives you `rpc.time`, which is your
per-operation server latency."""),

dict(id="s3", cat="File Protocols", title="S3",
     q="What is S3?",
     a="""**S3** (Simple Storage Service) is an object storage protocol and API,
originally from AWS and now the de facto industry standard — implemented by many
vendors including FlashBlade.

## The model
Data is stored as **objects**: the data itself, plus user metadata, plus a
**key**. Objects live in **buckets**, which are flat — there is no real directory
tree. Prefixes and delimiters simulate folders in listings.

Objects are **immutable**: you replace an object, you do not edit it in place.
There are no partial in-place writes and no POSIX semantics — no permissions
bits, no locking, no rename.

Access is over **HTTP/HTTPS via a REST API**. It is not mounted as a filesystem.

## Versus file and block
No POSIX semantics, but in exchange: near-limitless scale, rich per-object
metadata, HTTP-native access from anywhere, and simple flat namespace management.
Suits backups, archives, media, data lakes, and analytics — not databases or
anything needing in-place modification.

## Authentication
Access key ID + secret access key, with requests signed using **AWS Signature
Version 4**. The signature covers a timestamp, which is why **clock skew produces
403 errors**. Authorization comes from bucket policies, IAM policies, and ACLs.

## Core operations
`PUT` / `GET` / `DELETE` / `HEAD` object, `ListObjectsV2`, and **multipart
upload** for large objects (upload in parts, then complete).

## In a FlashBlade context
S3 is served on the same data VIPs as NFS and SMB. You create an account, then a
user within it, then generate an access key pair, and point the client at the
endpoint."""),

dict(id="s3req", cat="File Protocols", title="Sending S3 requests",
     q="How do you send S3 requests?",
     a="""## AWS CLI against a non-AWS endpoint
```
aws configure --profile fb           # access key ID + secret access key

aws --profile fb --endpoint-url https://10.0.5.20 s3 ls
aws --profile fb --endpoint-url https://10.0.5.20 s3 mb s3://mybucket
aws --profile fb --endpoint-url https://10.0.5.20 s3 cp ./file.txt s3://mybucket/
aws --profile fb --endpoint-url https://10.0.5.20 s3 sync ./dir s3://mybucket/dir
aws --profile fb --endpoint-url https://10.0.5.20 s3 ls s3://mybucket --recursive
```
`--no-verify-ssl` gets you past a self-signed certificate in a lab. Never in
production.

## Low-level s3api for full control
```
aws --profile fb --endpoint-url https://10.0.5.20 s3api list-objects-v2 \\
    --bucket mybucket --max-items 10
aws --profile fb --endpoint-url https://10.0.5.20 s3api head-object \\
    --bucket mybucket --key file.txt
aws --profile fb --endpoint-url https://10.0.5.20 s3api get-bucket-policy \\
    --bucket mybucket
```
`s3` is the friendly command set; `s3api` maps one-to-one onto API calls and is
what you want when reproducing a customer's exact request.

## Other clients
`s3cmd`, `mc` (MinIO client), `rclone`, and **boto3** in Python.
```python
import boto3
s3 = boto3.client("s3", endpoint_url="https://10.0.5.20",
                  aws_access_key_id="...", aws_secret_access_key="...")
print(s3.list_objects_v2(Bucket="mybucket"))
```

## Raw curl
Possible, but you must compute the SigV4 signature by hand. Almost always the
wrong tool — use the CLI or an SDK.

## Troubleshooting
- **403 SignatureDoesNotMatch** — clock skew, wrong secret, or a proxy altering
  headers. Check NTP first.
- **403 AccessDenied** — the key is valid but policy denies it.
- **404** — distinguish `NoSuchBucket` from `NoSuchKey`.
- `--debug` prints the canonical request being signed, which is how you find the
  header that does not match."""),

# === Permissions ============================================================
dict(id="acl", cat="Permissions & Identity", title="ACLs",
     q="What is an ACL?",
     a="""An **Access Control List** is an ordered list of **Access Control Entries**,
each granting or denying specific permissions to a specific principal (user,
group, or SID). ACLs are far more granular than POSIX mode bits, which can only
express owner / group / other with rwx.

## Flavours you will meet
- **NTFS / Windows ACLs** — SIDs, a rich permission set, inheritance flags, and
  **explicit deny** entries that override allows.
- **NFSv4 ACLs** — deliberately modelled on the Windows ACL model, which is what
  makes multiprotocol access workable.
- **POSIX draft ACLs** on Linux (`getfacl`/`setfacl`) — an *extension* to mode
  bits, and **not** the same model as NFSv4 ACLs. Translating between them is
  lossy, which is a real source of multiprotocol permission surprises.

```
getfacl /data/share
setfacl -m u:dylan:rwx /data/share
setfacl -m g:engineering:rx /data/share
setfacl -m d:u:dylan:rwx /data/share      # default (inherited) entry
setfacl -x u:dylan /data/share
nfs4_getfacl /mnt/data/file               # NFSv4 ACLs
icacls C:\\share                           # Windows
```

A **`+`** at the end of `ls -l` output — `-rw-rw-r--+` — means an ACL is present
beyond the mode bits. If permissions look right in `ls -l` but access is denied,
look for that plus sign.

**Correction to your note:** LDAP and SCCM are not the right anchors here — LDAP
is a directory protocol and SCCM is endpoint management. The reference points for
ACLs are **NTFS ACLs** and **NFSv4 ACLs**."""),

dict(id="posix", cat="Permissions & Identity", title="POSIX mode bits",
     q="What are POSIX mode bits?",
     a="""The base Unix permission model: three permission triplets — **owner, group,
other** — each with read (4), write (2), and execute (1).

`-rwxr-xr-x` = **755**. The first character is the **file type**:
`-` regular · `d` directory · `l` symlink · `b` block device · `c` char device ·
`s` socket · `p` named pipe

## On directories the bits mean something different
- **r** — list the names in the directory
- **w** — create, delete, and rename entries (note: **delete depends on the
  directory's** write bit, not the file's — this surprises people)
- **x** — traverse/enter the directory and stat its contents

You need **x on every parent directory** in a path. A file at `/data/a/b/file.txt`
with mode 644 is still unreachable if `/data/a` is missing execute for you.

```
chmod 640 file
chmod u+x,g-w file
chmod -R g+rX /data/share        # capital X: dirs and already-executable files
chown dylan:engineering file
stat -c '%a %U %G %n' file
umask                            # default 022 → 755 dirs, 644 files
```

`ls -l` plus `id` plus `stat` answers most "why can't I write here" questions in
about ten seconds."""),

dict(id="sticky", cat="Permissions & Identity", title="Sticky bit",
     q="What is the sticky bit?",
     a="""On a **directory**, the sticky bit restricts deletion and renaming of files to
the file's owner, the directory's owner, or root — **even when the directory is
world-writable**. It stops users from removing each other's files in shared space.

It appears as **`t`** in the other-execute position: `drwxrwxrwt` = **1777**.
A capital **`T`** means the sticky bit is set but the other-execute bit is not —
usually a mistake.

```
chmod +t /shared
chmod 1777 /shared
ls -ld /tmp                      # drwxrwxrwt
```

The canonical example is **`/tmp`**: everyone needs to create files there, but
nobody should be able to delete anyone else's.

On regular files the sticky bit is a legacy no-op on modern Linux (it originally
told the kernel to keep the executable's text segment in swap)."""),

dict(id="setuid", cat="Permissions & Identity", title="setuid and setgid",
     q="What are setuid and setgid?",
     a="""## setuid (4000)
An executable with setuid runs with the **effective UID of the file's owner**
rather than the calling user. Shown as **`s`** in the owner-execute position:
`-rwsr-xr-x`.

The canonical example is `/usr/bin/passwd` — owned by root and setuid, so an
ordinary user can update their own entry in `/etc/shadow`, which they cannot
otherwise read.

## setgid (2000)
- On an **executable**: runs with the file's group.
- On a **directory**: new files and subdirectories **inherit the directory's
  group** instead of the creator's primary group, and subdirectories inherit the
  setgid bit too. Shown as `drwxrwsr-x`.

The directory behaviour is the important one — it is the standard way to build a
shared group workspace where everything created stays owned by the project group.

```
chmod u+s /path/to/binary
chmod g+s /shared/project
chmod 2775 /shared/project       # setgid + rwxrwxr-x
find / -perm -4000 -type f 2>/dev/null    # audit setuid binaries
```

## Security
setuid-root binaries are a major privilege-escalation surface. Filesystems can be
mounted **`nosuid`**, and NFS exports commonly set `nosuid` — worth knowing,
because it explains why a setuid binary that works locally does nothing over NFS.

A capital **`S`** means the bit is set without the corresponding execute bit —
almost always an error."""),

dict(id="netgroup", cat="Permissions & Identity", title="Netgroups",
     q="What is a netgroup?",
     a="""A **netgroup** is an NIS (and now LDAP/IPA) construct defining a named group of
**(host, user, domain)** triples, used to apply access rules across many systems
from one central definition. Referenced with an `@` prefix.

```
engineering  (server1,dylan,corp.local) (server2,-,corp.local)
```
A `-` in a field is a wildcard-none — it matches nothing for that field, so
`(server2,-,corp.local)` means "the host server2, no particular user."

## Where they get used
```
/data  @engineering(rw,sec=sys)      # /etc/exports
```
Also in `/etc/hosts.allow`, and historically as `+@group` entries in `/etc/passwd`.

```
getent netgroup engineering
innetgr engineering server1 dylan corp.local
ypcat -k netgroup                    # NIS
```

## What breaks
In modern environments netgroups live in **LDAP or FreeIPA**, not NIS, and
resolution depends on `/etc/nsswitch.conf` pointing at the right source. Nested
netgroups are supported but resolution depends on the backend.

The classic symptom: an NFS export rule using `@netgroup` does not match a client
that should be a member. Check `getent netgroup <name>` **on the NFS server** —
if it returns nothing, the server cannot resolve the netgroup and the rule can
never match, regardless of what the directory contains."""),

dict(id="kerberos", cat="Permissions & Identity", title="Kerberos",
     q="What is Kerberos, how does the handshake work, and how does it affect data access?",
     a="""**Kerberos** is a ticket-based network authentication protocol (from MIT, and
the basis of Windows AD authentication). It lets principals prove identity
**without sending passwords over the network**, using symmetric cryptography and
a trusted third party: the **KDC** (Key Distribution Center), which contains the
**AS** (Authentication Service) and the **TGS** (Ticket Granting Service).
Port **88**.

## The exchange
1. **AS-REQ** — the client requests a TGT for its principal. With
   pre-authentication (the default), it includes a timestamp encrypted with the
   key derived from the user's password.
2. **AS-REP** — the KDC validates it and returns a **TGT** encrypted with the
   *krbtgt* account's key (opaque to the client), plus a session key encrypted
   with the user's own key.
3. **TGS-REQ** — the client wants a service. It sends the TGT, an authenticator,
   and the target service's **SPN**.
4. **TGS-REP** — the TGS returns a **service ticket** encrypted with the *service
   account's* key, plus a new session key.
5. **AP-REQ** — the client presents the service ticket and an authenticator to
   the service itself. The service decrypts it with its own key — **it never
   contacts the KDC**.
6. **AP-REP** — optional, for mutual authentication: the service proves its
   identity back to the client.

## Authentication is not authorization
Kerberos proves **who you are**. What you can then access is decided separately
by ACLs and group membership. (In AD, the **PAC** inside the ticket carries the
user's group SIDs, which the service uses for authorization.)

So: if Kerberos fails, access fails **regardless of correct permissions**. And if
Kerberos succeeds but you still get access denied, stop looking at Kerberos — the
problem is the ACL.

## The three classic failure causes
- **Clock skew** beyond 5 minutes — tickets are timestamped. Check NTP first.
- **DNS / reverse-DNS mismatch** — the client canonicalizes the name it connects
  to; if the PTR disagrees, ticket requests go to the wrong SPN.
- **Missing or duplicate SPN.**

```
kinit dylan@CORP.LOCAL
klist                            # list cached tickets
klist -e                         # show encryption types
kvno cifs/fb01.corp.local        # can I actually get a ticket for this service?
kdestroy
klist -k /etc/krb5.keytab        # principals in the keytab
```
Config lives in `/etc/krb5.conf`. On Windows: `klist`, `klist purge`.

## Storage relevance
NFS security flavours: **`krb5`** (authentication), **`krb5i`** (+ integrity),
**`krb5p`** (+ privacy/encryption). SMB uses Kerberos by default in an AD domain
and falls back to NTLM — **seeing an NTLM fallback in a capture is a strong
signal that Kerberos broke.**"""),

dict(id="spn", cat="Permissions & Identity", title="SPN",
     q="What is an SPN?",
     a="""A **Service Principal Name** is the unique identifier for a service instance in
Kerberos, in the form:

```
service/hostname[:port][/servicename]

cifs/fb01.corp.local
nfs/fb01.corp.local
HTTP/portal.corp.local
MSSQLSvc/db01.corp.local:1433
```

## How it is used
The client builds the SPN from **the hostname it used to connect** and asks the
KDC for a ticket for that SPN. The KDC looks up which account owns the SPN and
encrypts the service ticket with that account's key. The service can then decrypt
the ticket because it holds the same key.

That means the SPN is the link between "the name the client typed" and "the
account that can decrypt the ticket." Break the link and Kerberos fails.

## The three ways it breaks
- **Missing SPN** — the KDC returns `KDC_ERR_S_PRINCIPAL_UNKNOWN`. The client
  usually falls back to NTLM, so the symptom is "it works but it is not using
  Kerberos," or an outright failure if NTLM is disabled.
- **Duplicate SPN** registered on two accounts — Kerberos fails for **both**.
  A top-tier AD problem, and easy to create by rejoining a machine to the domain.
- **Name mismatch** — connecting via a CNAME alias or an **IP address** that is
  not a registered SPN. Connecting by IP generally cannot use Kerberos at all,
  which is why `\\\\10.0.5.20\\share` behaves differently from
  `\\\\fb01.corp.local\\share`.

```
setspn -L FB01$                          # list SPNs on an account
setspn -Q cifs/fb01.corp.local           # who owns this SPN?
setspn -X                                # find duplicates across the forest
setspn -S cifs/fb01.corp.local FB01$     # add, checking for duplicates first

Get-ADComputer fb01 -Properties servicePrincipalName

kvno cifs/fb01.corp.local                # Linux: can I get a ticket?
klist -k /etc/krb5.keytab                # principals present in the keytab
```
`setspn -X` on a Kerberos case is often the fastest path to root cause."""),

dict(id="ad", cat="Permissions & Identity", title="Active Directory",
     q="What is Active Directory?",
     a="""**Active Directory** is Microsoft's directory service. It bundles four things
into one identity platform:
- An **LDAP** directory (the object database)
- A **Kerberos KDC** (authentication)
- **DNS** integration, with SRV records for service location
- **Group Policy** (configuration management)

## Structure
**Forest** (top-level security and schema boundary) → **Domain** (replication and
policy boundary) → **Organizational Units** (delegation and GPO targets) →
**objects** (users, groups, computers, service accounts).

**Domain Controllers** hold the database (`NTDS.dit`) and replicate multi-master;
a handful of **FSMO** roles are single-master (Schema Master, Domain Naming
Master, RID Master, PDC Emulator, Infrastructure Master).

Objects are identified internally by **SID** and in LDAP by **distinguished name**:
`CN=Dylan,OU=Users,DC=corp,DC=local`.

Groups have a **type** (security vs distribution) and a **scope** (domain-local,
global, universal).

```
nltest /dsgetdc:corp.local        # which DC am I using?
w32tm /query /status              # time sync — Kerberos depends on it
Get-ADUser dylan -Properties *
Get-ADGroupMember "Storage Admins"
gpresult /r

realm discover corp.local         # from Linux
realm join corp.local
adcli info corp.local
wbinfo -u ; wbinfo -g
id dylan@corp.local
```

## Storage relevance
Joining an array to AD provides SMB authentication via Kerberos, SID-to-UID
mapping for multiprotocol access, and group-based ACLs. When a domain join fails
or breaks later, the cause is nearly always one of three things: **DNS**, **time
sync**, or the **computer account / SPN**. Check them in that order."""),

dict(id="ldap", cat="Permissions & Identity", title="LDAP",
     q="What is LDAP?",
     a="""**LDAP** (Lightweight Directory Access Protocol) is the protocol for querying
and modifying a hierarchical directory, derived from X.500. Port **389** for
plaintext or StartTLS; **636 for LDAPS** (TLS from connection start).

## Structure
Entries form a tree (the DIT). Each entry has a **distinguished name (DN)** built
from relative DNs, and a set of **attributes** whose allowed shape is defined by
**objectClasses** in the schema.

```
uid=dylan,ou=people,dc=corp,dc=local
```

## Operations
bind (authenticate), search, compare, add, modify, modifyDN, delete, unbind.

A search takes a **base DN**, a **scope** (base / one / sub), and a **filter**:
```
(&(objectClass=user)(sAMAccountName=dylan))
(|(cn=dylan*)(mail=dylan@*))
(&(objectClass=group)(member=CN=Dylan,OU=Users,DC=corp,DC=local))
```
`&` is AND, `|` is OR, `!` is NOT — prefix notation.

## On Linux
LDAP is the backend for user and group lookup via **SSSD** (or nslcd), wired in
through `/etc/nsswitch.conf`. This is how `id dylan` returns a UID and GID that
came from the directory — and therefore how NFS file ownership resolves to names.

```
ldapsearch -x -H ldaps://dc01.corp.local -D "corp\\\\dylan" -W \\
  -b "dc=corp,dc=local" "(sAMAccountName=dylan)" uidNumber gidNumber memberOf
ldapwhoami -x -H ldap://dc01.corp.local -D "..." -W
getent passwd dylan
id dylan
sssctl user-checks dylan
```

## AD vs LDAP — the distinction to state
AD **speaks** LDAP, but AD is much more than LDAP. LDAP is the query protocol;
AD is the full platform (directory + Kerberos + DNS + Group Policy). OpenLDAP and
389 Directory Server are pure LDAP directories with no Kerberos or GPO layer."""),

# === Linux ==================================================================
dict(id="sed", cat="Linux Commands", title="sed",
     q="What is sed and how do you use it?",
     a="""**sed** is the stream editor — it applies edits to a stream line by line
without opening the file interactively. Ideal for scripted edits and for slicing
large logs.

```
sed 's/old/new/' file            # first match on each line
sed 's/old/new/g' file           # every match
sed -i 's/old/new/g' file        # edit in place
sed -i.bak 's/old/new/g' file    # in place, keeping a .bak
sed -n '10,20p' file             # print lines 10-20 only
sed '/^#/d' file                 # drop comment lines
sed '/^$/d' file                 # drop blank lines
sed -n '/ERROR/p' file           # print matching lines (like grep)
sed -E 's/([0-9]{1,3}\\.){3}[0-9]{1,3}/x.x.x.x/g' file   # redact IPs
```

## The one worth memorising
Extract a time window from a log — hugely useful and much faster than eyeballing:
```
sed -n '/Jul 28 09:00/,/Jul 28 10:00/p' /var/log/messages
```
The `/start/,/end/` range form works on any pattern pair.

Always test without `-i` first. `-i` with a bad expression silently destroys the
file."""),

dict(id="watch", cat="Linux Commands", title="watch",
     q="What does watch do?",
     a="""**watch** re-runs a command at a fixed interval and displays the output
full-screen, refreshing in place. Default interval is **2 seconds**.

```
watch multipath -ll
watch -n 1 'ss -s'                        # every second
watch -d 'nfsstat -c'                     # -d highlights what changed
watch -n 5 -d 'df -h /mnt/data'
watch -n 1 'grep -c ERROR /var/log/messages'
watch -t -n 1 'ip -s link show eth0'      # -t drops the header
```

**`-d` is the option to remember** — it highlights the characters that changed
since the last refresh, which turns watch from "output scrolling past" into an
actual change detector. Watching error counters increment on an interface, or a
multipath path flapping, is exactly what it is for.

Quote the command if it contains pipes or globs, or the shell expands them once
instead of on every iteration."""),

dict(id="grep", cat="Linux Commands", title="grep",
     q="How do you grep for phrases and patterns?",
     a="""**grep** searches input for lines matching a pattern.

```
grep "connection refused" /var/log/messages     # quote phrases with spaces
grep -i error file               # case-insensitive
grep -r "pattern" /var/log       # recursive
grep -n pattern file             # show line numbers
grep -c pattern file             # count matching LINES
grep -v pattern file             # invert — lines that do NOT match
grep -w nfs file                 # whole word only (not "nfsd", "nfsstat")
grep -l pattern *.log            # list filenames only
grep -o pattern file             # print only the matched text
grep -A3 -B3 pattern file        # 3 lines after / before
grep -C3 pattern file            # 3 lines of context both sides
```

## Phrases specifically
Quote them. Use `-F` for a fixed string when the phrase contains regex
metacharacters — it is also faster:
```
grep -F "no such file or directory" /var/log/messages
grep -Fi "connection reset by peer" /var/log/messages
```

## Multiple patterns
```
grep -Ei "error|critical|warning" /var/log/messages
grep -E "(timeout|refused|denied)" /var/log/messages
```
`-E` enables extended regex, which is what makes `|` work without backslashes.

## Chaining
```
grep -i fb01 /var/log/messages | grep -Ei "error|warn"
tail -f /var/log/messages | grep --line-buffered -i error
```
**`--line-buffered`** matters when grep is in the middle of a pipe following
`tail -f` — without it, grep buffers and output appears in bursts."""),

dict(id="tail", cat="Linux Commands", title="tail and head",
     q="How do you view the end (or start) of a file?",
     a="""```
tail file                        # last 10 lines
tail -n 100 file                 # last 100
tail -f /var/log/messages        # follow as it grows
tail -F /var/log/messages        # follow AND survive rotation
tail -f file | grep --line-buffered -i error
tail -n +50 file                 # from line 50 to the end

head file                        # first 10 lines
head -n 50 file
head -n 20 file | tail -n 5      # lines 16-20
```

## -f versus -F
**`-F` is what you want for a rolling log.** `-f` follows the file *descriptor* —
when logrotate renames the file and creates a new one, `-f` keeps watching the
old, now-renamed file and appears to go silent. `-F` follows the file *name* and
reopens it, so you keep seeing new entries.

For large log files, `tail` and `less` are the right tools. Never `cat` or `vi` a
multi-gigabyte log on a production box."""),

dict(id="systemctl", cat="Linux Commands", title="systemctl",
     q="How do you manage services with systemctl?",
     a="""**systemctl** controls systemd units — services, sockets, timers, mounts,
targets.

```
systemctl status nfs-server
systemctl start nfs-server
systemctl stop nfs-server
systemctl restart nfs-server
systemctl reload nfs-server           # re-read config without dropping state
systemctl enable --now nfs-server     # start now and at boot
systemctl disable nfs-server
systemctl is-active nfs-server
systemctl is-enabled nfs-server

systemctl list-units --type=service
systemctl list-units --type=service --state=failed
systemctl --failed
systemctl cat nfs-server              # show the unit file
systemctl edit nfs-server             # create an override drop-in
systemctl daemon-reload               # REQUIRED after editing unit files
systemctl list-dependencies nfs-server
```

Two things that catch people out:
- **`daemon-reload`** is required after any unit file change, or systemd keeps
  running the old definition.
- `systemctl status` shows only the last few log lines. Use `journalctl -u <unit>`
  for the full picture."""),

dict(id="journalctl", cat="Linux Commands", title="journalctl",
     q="How do you query the systemd journal?",
     a="""**journalctl** queries the systemd journal — the structured, indexed log store
that replaces (or supplements) `/var/log/messages` on systemd systems.

```
journalctl -u nfs-server                    # one unit
journalctl -u nfs-server -f                 # follow
journalctl -n 100                           # last 100 entries
journalctl --since "1 hour ago"
journalctl --since "2026-07-28 08:00" --until "2026-07-28 09:00"
journalctl -p err                           # priority err and above
journalctl -p warning -b                    # this boot
journalctl -b -1                            # previous boot
journalctl -k                               # kernel messages only
journalctl -o short-precise                 # microsecond timestamps
journalctl _PID=1234
journalctl --disk-usage
journalctl --vacuum-time=7d
```

## Points worth knowing
- **`-p` is inclusive of higher severity**: `-p warning` gives warning, err,
  crit, alert, and emerg. Levels are emerg(0) through debug(7).
- Time filters accept human phrasing: `"10 min ago"`, `yesterday`, `today`.
- Combining `--since`, `-u`, and `-p` narrows a noisy system to the relevant
  window in one command — much cleaner than grep pipelines against a flat file.
- If the journal is volatile (`Storage=volatile`), it is lost on reboot. Check
  `/etc/systemd/journald.conf` before promising a customer historical logs."""),

dict(id="find", cat="Linux Commands", title="find",
     q="How do you use find?",
     a="""**find** walks a directory tree and matches files by attribute.

```
find /var/log -name "messages*"
find /var/log -iname "*.LOG"          # case-insensitive
find /data -type f                    # files only  (-type d for directories)
find /var/log -mtime -1               # modified in the last day
find /var/log -mmin -30               # last 30 minutes
find /data -size +100M
find /data -user dylan
find / -perm -4000 -type f 2>/dev/null    # setuid audit
find /data -maxdepth 2 -type d
find /data -empty
```

## Acting on results
```
find /var/log -name "*.gz" -exec zgrep -H ERROR {} \\;
find /var/log -name "*.gz" -exec zgrep -H ERROR {} +      # batched, faster
find /var/log -name "messages*" -print0 | xargs -0 zgrep -Hi error
find /tmp -name "core.*" -mtime +7 -delete
```

`-print0` with `xargs -0` handles filenames containing spaces — worth defaulting
to. `2>/dev/null` suppresses permission-denied noise when searching from `/`.

Order matters: `find /path -name X -mtime -1` applies tests left to right, so put
the cheapest, most selective test first on large trees."""),

dict(id="tcpdump", cat="Linux Commands", title="tcpdump",
     q="How do you capture packets with tcpdump?",
     a="""**tcpdump** is a command-line packet analyzer. It captures traffic entering or
leaving an interface and either prints it or writes a pcap for Wireshark.

```
tcpdump -i eth0 -nn host 10.0.5.20
tcpdump -i eth0 -nn -s 0 -w /tmp/cap.pcap host 10.0.5.20 and port 2049
tcpdump -i any -nn port 445
tcpdump -i eth0 -nn -c 1000 tcp port 2049
tcpdump -i eth0 -nn -C 100 -W 10 -w /tmp/cap.pcap    # 10 files x 100MB, rotating
tcpdump -r /tmp/cap.pcap -nn | head -50              # read a file back
```

## Options
- `-nn` — do not resolve names or ports (faster, and avoids DNS side effects)
- `-s 0` — capture the full packet (older versions truncated by default)
- `-w` — write pcap · `-r` — read pcap
- `-c N` — stop after N packets
- `-C <MB> -W <count>` — rotating files, bounded total size
- `-v` / `-vv` — more detail · `-A` — print payload as ASCII
- `-e` — show the link-layer header (needed to see VLAN tags and MACs)

## BPF filters
```
host 10.0.5.20
net 10.0.5.0/24
port 445
tcp port 2049
src host 10.0.1.5 and dst port 443
icmp
vlan 100
not port 22                      # exclude your own SSH session
```

**Always bound your capture.** A filter plus `-c` or `-C/-W` prevents filling the
disk on a production host — an unbounded tcpdump on a busy array-facing interface
will do real damage. Adding `not port 22` keeps your own session out of the file."""),

dict(id="ss", cat="Linux Commands", title="ss",
     q="What is ss and how does it compare to netstat?",
     a="""**ss** (socket statistics) is the modern replacement for netstat. It reads
kernel socket data directly, so it is substantially faster on hosts with many
connections.

```
ss -tulpn                        # TCP+UDP listening, numeric, with process
ss -tan                          # all TCP, numeric
ss -s                            # summary counts by state
ss -tp state established
ss -tn dst 10.0.5.20             # connections to a specific host
ss -tn '( dport = :2049 )'       # to a specific port
ss -ti                           # TCP internals: rtt, cwnd, retransmits
ss -tan state time-wait | wc -l
ss -tm                           # socket memory usage
```

## The flag that earns its keep
**`ss -ti`** exposes per-connection RTT, congestion window, and retransmission
counts straight from the kernel. When a customer says "the network is slow,"
retransmits and RTT on the actual storage connection are hard evidence — no
packet capture required.

Same caveat as netstat: `ss` shows sockets on the **local** machine. For a remote
host, use `nmap` or `nc -zv`."""),

dict(id="ls", cat="Linux Commands", title="Listing files",
     q="How do you show all files in a directory?",
     a="""```
ls                    # names only
ls -l                 # long format: permissions, owner, group, size, mtime
ls -a                 # include hidden dotfiles
ls -la                # both — the everyday default
ls -lh                # human-readable sizes
ls -ltr               # sort by time, oldest first — best for log directories
ls -lS                # sort by size
ls -lR                # recursive
ls -li                # show inode numbers
ls -ld /data          # the directory itself, not its contents
```

**Correction to your note:** `ls -I` (capital i) is `--ignore=PATTERN` — it
*excludes* matching files. What you want to show hidden files is **`ls -a`**
(lowercase). It is an easy typo to carry forward, and it does the opposite of
what you intended.

## Reading `ls -l` output
```
-rw-rw-r--+ 1 dylan engineering 4096 Jul 28 09:14 notes.txt
^          ^                                      
type       ACL present
```
The trailing **`+`** means an ACL exists beyond the mode bits. A **`.`** there
means an SELinux context. If permissions look correct but access is denied, that
character is the first thing to notice.

`ls -ltr` is the one to build muscle memory for — in a log directory, the newest
file ends up at the bottom, right above your prompt."""),

dict(id="openfile", cat="Linux Commands", title="Opening and viewing files",
     q="How do you open or view a file from the Linux CLI?",
     a="""## Editing
```
vi file      vim file      nano file
```

## Viewing without editing — safer, especially on logs
```
less file            # the right default
more file
cat file             # small files only
head -n 50 file
tail -n 50 file
view file            # vi in read-only mode
zless file.gz        # compressed
```

## less navigation (worth knowing properly)
- `/text` search forward · `?text` search backward · `n` / `N` next / previous
- `G` end of file · `g` start · space page down · `b` page up
- **`F`** follow mode — behaves like `tail -f`, and `Ctrl-C` drops back to
  normal browsing. Very useful: watch a live log, then immediately scroll back.
- `-N` shows line numbers · `q` quits

## vi essentials
`i` insert · `Esc` command mode · `:w` write · `:q` quit · `:wq` write and quit ·
`:q!` discard changes · `/text` search · `dd` delete line · `u` undo ·
`Shift-G` end of file

## The practical rule
On a multi-gigabyte log, use `less` or `tail`. Never `cat` (floods the terminal)
and never `vi` (loads the whole file into memory)."""),

dict(id="ps", cat="Linux Commands", title="Viewing processes",
     q="How do you view currently running processes?",
     a="""## Snapshot — ps
```
ps aux                           # BSD style, all processes
ps -ef                           # SysV style, all processes
ps auxf                          # ASCII process tree
ps -eo pid,ppid,user,%cpu,%mem,etime,stat,cmd --sort=-%cpu | head -20
ps aux | grep -v grep | grep nfsd
pgrep -a nfsd                    # PIDs and command lines
pstree -p
```

## Live — top
```
top
```
Inside top: **`M`** sort by memory · **`P`** sort by CPU · `1` show per-core ·
`c` full command line · `k` kill a PID · `u` filter by user · `q` quit.

`htop` is nicer if it is installed — scrollable, colour-coded, mouse-aware.

## Reading the STAT column
`R` running · `S` interruptible sleep (normal) · **`D` uninterruptible sleep** ·
`Z` zombie · `T` stopped. Suffixes: `s` session leader, `+` foreground, `<` high
priority.

**`D` state is the one that matters in storage support.** A process stuck in `D`
is blocked in a kernel I/O call and cannot be killed, not even with `kill -9`.
Several processes in `D` state pointing at the same mount usually means a hung
NFS mount or a dead storage path — and it tells you the problem is below the
application, not in it."""),

dict(id="misccmds", cat="Linux Commands", title="Other commands worth knowing",
     q="What other Linux commands come up regularly in storage support?",
     a="""## Files and disk
```
df -h                            # filesystem usage
df -i                            # inode usage — full inodes look like a full disk
du -sh /data/*                   # what is consuming space
du -sh --max-depth=1 /data | sort -h
lsof +D /mnt/data                # what has files open under a path
lsof -i :2049                    # what is using a port
lsof -p 1234
```

## Storage path
```
multipath -ll                    # paths and their state
lsscsi
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,WWN
dmesg -T | grep -i -E "scsi|multipath|i/o error"
nfsstat -m                       # mount options actually in effect
nfsstat -c                       # client-side operation counts
iostat -xz 1                     # per-device latency and utilisation
```

## Text processing
```
awk '{print $1, $5}' file
awk '$3 > 100 {print}' file
sort file | uniq -c | sort -rn   # count and rank — the workhorse
cut -d: -f1 /etc/passwd
tr -s ' '                        # squeeze repeated spaces
wc -l file
```

## Network and system
```
nc -zv 10.0.5.20 2049
nmap -p 22,445,2049 10.0.5.20
ethtool eth0                     # link, speed, duplex
ip -s link                       # interface errors and drops
dmesg -T                         # human-readable timestamps
uptime ; free -h ; vmstat 1
strace -p 1234                   # what syscall is it stuck in
```

`sort | uniq -c | sort -rn` is the single most reusable pipeline in log analysis
— it turns any repetitive log into a ranked frequency table."""),

# === Log analysis ===========================================================
dict(id="logquery", cat="Log Analysis", title="Querying logs for errors",
     q="Give an example of an NFS log query for errors, critical, and warning in /var/log/messages for a specific hostname. What is the syntax?",
     a="""## The direct answer
```
grep -Ei "error|critical|warning" /var/log/messages | grep -i "fb01"
```
Or in one pass, requiring both on the same line:
```
grep -Ei "fb01.*(error|critical|warning)" /var/log/messages
```

## Better in practice
Add context lines and line numbers so you can see what surrounded the error:
```
grep -Ein "error|critical|warn" /var/log/messages | grep -i fb01
grep -Ei "error|crit|warn" /var/log/messages | grep -i fb01 -A3 -B3
```
Use `crit` and `warn` rather than the full words — logs are inconsistent about
`WARN` vs `WARNING` and `CRIT` vs `CRITICAL`.

## Scope it to NFS specifically
```
grep -Ei "nfs|rpc|mountd|statd|lockd" /var/log/messages | \\
  grep -i fb01 | grep -Ei "error|crit|warn|denied|timeout|stale"
```

## Bound it to a time window
```
sed -n '/Jul 28 09:00/,/Jul 28 10:00/p' /var/log/messages | \\
  grep -Ei "fb01.*(error|crit|warn)"

awk '/Jul 28 09:/,/Jul 28 10:/' /var/log/messages | grep -Ei "error|crit|warn"
```

## On a systemd host, prefer the journal
```
journalctl -u nfs-server --since "1 hour ago" -p warning
journalctl --since "2026-07-28 08:00" --until "2026-07-28 09:00" -p err | grep -i fb01
journalctl -p err -b | grep -Ei "nfs|rpc"
```
Remember `-p warning` is **inclusive of higher severity** — you get warning, err,
crit, alert, and emerg, which is normally what you want.

## NFS-specific strings worth grepping for
`stale file handle` · `server not responding` · `access denied by server` ·
`RPC: Timed out` · `nfs: server ... not responding, still trying` ·
`mount.nfs: Connection timed out` · `NFS4ERR_` · `no such device`"""),

dict(id="rollinglogs", cat="Log Analysis", title="Searching rolling logs",
     q="How do you search multiple directories if a file is rolling?",
     a="""When logrotate is active you have `messages`, `messages.1`, `messages-20260728`,
and compressed `messages.2.gz` — a plain grep of `messages` misses most of it.

## Include rotated and compressed files
```
grep -Ei "error|timeout" /var/log/messages*        # uncompressed rotations
zgrep -Ei "error|timeout" /var/log/messages*.gz    # compressed only
```

## Both in one pass
```
zgrep -Hi "nfs.*error" /var/log/messages*
```
**`zgrep` handles uncompressed files too**, so a single `zgrep` across the glob
covers everything. `-H` forces the filename prefix so you know which file matched
even when only one file matches.

## Time-bounded, using find
```
find /var/log -name "messages*" -mtime -7 -print0 | \\
  xargs -0 zgrep -Hi "nfs.*error"
```

## Across several directories
```
grep -rEi "error|critical" /var/log /var/log/pure /opt/app/logs --include="*.log"
find /var/log /opt/app/logs -name "*.log*" -mtime -3 -print0 | \\
  xargs -0 zgrep -Hi "timeout"
```

## Get the output in chronological order
Glob expansion sorts `messages.1` before `messages.10`, which is not time order:
```
ls -tr /var/log/messages* | xargs zgrep -Hi error
```
`-tr` sorts by mtime, oldest first, so the output reads forward in time.

## Following a live rolling file
```
tail -F /var/log/messages | grep --line-buffered -Ei "error|warn"
```
**`-F`** (capital) follows the file *name* and reopens it after rotation. Plain
`-f` follows the descriptor and goes silent the moment logrotate runs — the
classic "I left it running overnight and got nothing" mistake.
`--line-buffered` makes grep flush each line immediately through the pipe."""),

dict(id="countlogs", cat="Log Analysis", title="Counting log occurrences",
     q="How do you count how many times you see a specific message in a log?",
     a="""## Count matching lines
```
grep -c "connection refused" /var/log/messages
```

## Count actual occurrences (multiple per line)
```
grep -o "connection refused" /var/log/messages | wc -l
```
**`grep -c` counts lines, not matches.** If a message can appear twice on one
line, `-c` undercounts. This distinction is a genuine interview discriminator.

## Across rotated files
```
zgrep -Hc "connection refused" /var/log/messages*     # per file
zgrep -h "connection refused" /var/log/messages* | wc -l    # grand total
```
`-c` per file plus `-h` for the total is the pair to remember.

## Group and rank — the one you will actually use
Strip the timestamp fields, then count unique messages:
```
grep -i error /var/log/messages | awk '{$1=$2=$3=""; print}' | \\
  sort | uniq -c | sort -rn | head -20
```
This turns 50,000 lines into "here are the 20 distinct errors and how often each
occurred" — which is almost always the real question.

## Count per hour, to find a spike
```
grep -i "nfs.*error" /var/log/messages | \\
  awk '{print $1, $2, substr($3,1,2)}' | uniq -c
```

## Count per client IP
```
grep -i "denied" /var/log/messages | \\
  grep -oE "([0-9]{1,3}\\.){3}[0-9]{1,3}" | sort | uniq -c | sort -rn
```
Answers "is this one bad client or everybody?" — which changes the whole
direction of the case.

## With journalctl
```
journalctl -u nfs-server --since today | grep -c "timed out"
journalctl -p err --since today -o cat | sort | uniq -c | sort -rn | head
```"""),

# === Wireshark ==============================================================
dict(id="wsnfs", cat="Wireshark & Packet Analysis", title="NFS in a packet capture",
     q="What would you expect to see in a packet capture of an NFS workload?",
     a="""## Filters
```
nfs                              # NFS operations
rpc                              # the RPC layer beneath
tcp.port == 2049
nfs.status != 0                  # v3 errors
nfs.nfsstat4 != 0                # v4 errors
portmap || mount || nlm          # v3 side protocols
```

## Expected sequence — NFSv4.x
TCP three-way handshake to 2049 → `EXCHANGE_ID` / `CREATE_SESSION` (v4.1) or
`SETCLIENTID` + `SETCLIENTID_CONFIRM` (v4.0) → `PUTROOTFH` → a chain of `LOOKUP`
operations walking the path → `GETATTR` / `ACCESS` → `OPEN` → `READ` / `WRITE` →
`COMMIT` → `CLOSE`.

**v4.1 wraps operations in COMPOUND calls** with a leading `SEQUENCE` op, so one
packet carries many operations. Read the operations list *inside* the COMPOUND —
the packet summary alone will mislead you.

## Expected sequence — NFSv3
Discrete calls, no compounding: `NULL`, `GETATTR`, `LOOKUP`, `ACCESS`, `READ`,
`WRITE`, `COMMIT`, plus `MOUNT` and `PORTMAP` traffic on the side.

## What to actually look for
- **Every Call has a matching Reply.** Wireshark links them and computes
  **`rpc.time`** — the server response time. That is your latency measurement.
- **Error status codes**: `NFS4ERR_ACCESS`, `NFS4ERR_STALE`, `NFS4ERR_DELAY`,
  `NFS4ERR_GRACE`, `NFS3ERR_ACCES`, `NFS3ERR_JUKEBOX`. Filter with
  `nfs.status != 0`.
- **WRITE stability**: `UNSTABLE` writes followed by a `COMMIT` is normal async
  behaviour. `FILE_SYNC` on every write is synchronous and destroys throughput —
  a real finding.
- **I/O sizes** matching the negotiated `rsize`/`wsize`. Lots of small reads when
  you configured 1MB means the mount negotiated down.
- **TCP-layer problems**: retransmissions, duplicate ACKs, zero window. If these
  are present, the problem is the network, not the array.

## Fast path
Statistics → Service Response Time → ONC-RPC gives min/max/avg per procedure in
one table. Start there before reading individual packets."""),

dict(id="wssmb", cat="Wireshark & Packet Analysis", title="SMB handshake",
     q="What does an SMB handshake look like?",
     a="""Filter: `smb2` (or `tcp.port == 445`).

## The sequence
1. **TCP three-way handshake** to port 445.
2. **Negotiate Protocol Request / Response** — the client offers dialects
   (2.0.2 through 3.1.1), the server picks one. 3.1.1 adds pre-auth integrity
   negotiate contexts. The server advertises capabilities here: multichannel,
   encryption, large MTU.
3. **Session Setup Request / Response** — authentication, carried in a
   GSS-API/SPNEGO blob.
   - **Kerberos**: the blob contains an AP-REQ. Usually one round trip.
   - **NTLM**: you will see the NTLMSSP three-message exchange —
     NEGOTIATE → CHALLENGE → AUTH — so two round trips.
   - `STATUS_MORE_PROCESSING_REQUIRED` between the messages is **normal**, not an
     error.
4. **Tree Connect Request / Response** — connect to the share (`\\\\fb01\\data`),
   returns a TreeID.
5. **Create Request / Response** — open the file or directory, returns a FileID.
   This is where `STATUS_ACCESS_DENIED` and `STATUS_OBJECT_NAME_NOT_FOUND` appear.
6. Then the working traffic: **Read / Write / Ioctl / QueryInfo / SetInfo**,
   then **Close**, **Tree Disconnect**, **Logoff**.

## Troubleshooting tells
- **NTLM where you expected Kerberos** — SPN, DNS, or time problem. This is the
  single most valuable thing to spot in an SMB capture.
- `smb2.nt_status != 0` filters every failure in the capture at once.
- **Negotiated dialect** — if it lands on 2.0.2 you lose multichannel and
  encryption, which explains a lot of performance complaints.
- **SMB1 present at all** (`smb` filter, no `2`) is a red flag on its own.
- If signing or encryption is negotiated, payloads are opaque — you can still see
  the operation flow and timing, just not the data."""),

dict(id="wslatency", cat="Wireshark & Packet Analysis", title="Latency from a capture",
     q="How would you determine latency with a packet capture?",
     a="""First be specific about **which** latency — these are different numbers and
mixing them up is how people reach wrong conclusions.

## 1. Network round trip
The TCP handshake: time between **SYN** and **SYN-ACK**. Pure network RTT with no
application involvement. Also `tcp.analysis.ack_rtt` for ongoing measurement.

## 2. Server / application response time
Time between a request and its response.
- NFS: **`rpc.time`**
- SMB: **`smb2.time`**
This is the number that tells you whether the storage is slow.

## 3. Gaps between frames
`frame.time_delta_displayed` — but filter to one conversation first, or the
number is meaningless.

## Method
1. Filter to a single client/server conversation and one protocol.
2. Right-click the `rpc.time` or `smb2.time` field → **Apply as Column**.
3. Sort descending by that column.
4. Look at the slow operations and find the pattern: one procedure type? one
   file? one time window? one client?
5. Cross-check with **Statistics → Service Response Time** and
   **Statistics → Conversations**.

## Interpreting the result
- **High `rpc.time`, clean TCP layer** → the server/storage is slow. Real finding.
- **Low `rpc.time` but poor throughput** → client-side: serialization, single
  threaded I/O, or small I/O sizes. The storage is fine.
- **Retransmissions, dup ACKs, zero window** (`tcp.analysis.flags`) → network or
  receiver buffer problem, not storage.

## The trap
An idle client that simply is not sending requests looks "slow" to the user but
shows **tiny** response times in the capture. That capture is not a failure to
find the problem — it is proof the problem is client-side or in the application.
Being able to say that clearly is often the most valuable outcome of the analysis.

## CLI
```
tshark -r cap.pcap -Y "nfs" -T fields -e frame.number -e rpc.time | sort -k2 -rn | head
tshark -r cap.pcap -q -z rpc,srt,100003,3
tshark -r cap.pcap -q -z conv,tcp
```"""),

# === Windows ================================================================
dict(id="winevent", cat="Windows", title="Windows event history",
     q="How do you show the history of alerts and events on a Windows machine?",
     a="""**Event Viewer** — `eventvwr.msc`.

## Where things live
- **Windows Logs** → Application, Security, System, Setup, Forwarded Events
- **Applications and Services Logs** → per-component channels. For storage work:
  Microsoft → Windows → **SMBClient/Operational**, **SMBServer**, and disk/MPIO
  channels.

## Levels
Critical (1) · Error (2) · Warning (3) · Information (4) · Verbose (5)

## PowerShell — what you would actually use
```powershell
Get-WinEvent -LogName System -MaxEvents 50
Get-WinEvent -FilterHashtable @{LogName='System'; Level=2; StartTime=(Get-Date).AddHours(-1)}
Get-WinEvent -LogName 'Microsoft-Windows-SMBClient/Operational' -MaxEvents 100
Get-WinEvent -FilterHashtable @{LogName='System'; ID=153,129} | Format-List
Get-EventLog -LogName System -EntryType Error -Newest 20
```
`Get-WinEvent` is the current cmdlet; `Get-EventLog` is legacy and cannot read
the newer per-component channels.

## CMD
```
wevtutil qe System /c:20 /f:text /rd:true
wevtutil el                      # list all channels
```

## For storage cases specifically
- **System log** — disk, MPIO, iSCSI, and NIC events. Event IDs **129** (reset to
  device) and **153** (I/O retried) are the classic storage path complaints.
- **SMBClient/Operational** — session failures, reconnects, and dialect issues.
- Filter by a time window that brackets the reported incident, and always compare
  against the array's own logs for the same window."""),

dict(id="openports", cat="Windows", title="Checking open ports on another device",
     q="What command would you use to check for open ports on another device?",
     a="""## The key distinction first
- **`netstat` / `ss`** show ports open on the **local** machine.
- **`nmap` / `nc`** probe a **remote** machine.

Your note listed both for the remote case — netstat is the local half of that
pair. Worth stating cleanly, because it is a common mix-up.

## nmap — full port scanner
```
nmap -p 22,445,2049 10.0.5.20
nmap -p- 10.0.5.20               # all 65535 TCP ports
nmap -sT 10.0.5.20               # TCP connect scan (no root needed)
nmap -sS 10.0.5.20               # SYN / half-open scan (needs root)
nmap -sU -p 111,161 10.0.5.20    # UDP
nmap -Pn 10.0.5.20               # skip host discovery (host blocks ping)
nmap -sV -p 445 10.0.5.20        # service version detection
```
`-Pn` is the one to remember — without it, nmap gives up on hosts that do not
answer ping, which includes plenty of hardened systems.

## netcat — quick single-port check
```
nc -zv 10.0.5.20 2049
nc -zvu 10.0.5.20 161            # UDP
nc -zv 10.0.5.20 20-25           # port range
```

## Without netcat installed
```
timeout 2 bash -c '</dev/tcp/10.0.5.20/2049' && echo open || echo closed
curl -v telnet://10.0.5.20:445
```

## PowerShell
```powershell
Test-NetConnection -ComputerName 10.0.5.20 -Port 445
Test-NetConnection -ComputerName 10.0.5.20 -TraceRoute
```
`Test-NetConnection` is the modern replacement for `telnet host port` and reports
TCP test success, the route, and the source interface in one command.

**Get permission before scanning.** A port scan against customer infrastructure
can trip intrusion detection and become its own incident."""),

dict(id="ipcmds", cat="Windows", title="IP configuration commands",
     q="How do you get IP information on Linux and Windows?",
     a="""## Linux — modern
```
ip addr show
ip -br addr                      # brief, one line per interface
ip route show
ip route get 8.8.8.8             # which route/source would be used
ip link show                     # state and MTU
ip neigh show                    # ARP table
ip -s link                       # errors and drops per interface
```

## Linux — legacy
```
ifconfig
route -n
arp -an
netstat -i
```
**Note:** `ifconfig` and friends are part of `net-tools`, which is **deprecated**
and frequently not installed on minimal or container images. It also does not
show secondary addresses added with `ip addr add` — so a host can have an address
that `ip addr` shows and `ifconfig` does not. Use `ip`.

## Windows
```
ipconfig
ipconfig /all                    # MAC, DHCP, DNS servers, lease times
ipconfig /release
ipconfig /renew
ipconfig /flushdns
ipconfig /displaydns
route print
arp -a
getmac
```

## Windows PowerShell
```powershell
Get-NetIPConfiguration
Get-NetIPAddress
Get-NetAdapter
Get-NetRoute
Get-DnsClientServerAddress
Clear-DnsClientCache
```

`ipconfig /all` and `ip addr` are the two you reach for first in almost any
connectivity case — they answer address, mask, gateway, and DNS in one shot."""),

# === Methodology ============================================================
dict(id="troubleshooting", cat="Troubleshooting Method", title="Common troubleshooting commands",
     q="What are your common troubleshooting commands and what is your method?",
     a="""Work **bottom-up through the OSI stack**. Each layer you prove good narrows
the problem and gives you something concrete to hand off.

## L1 — physical
```
ethtool eth0                     # link detected, speed, duplex
ip -s link                       # errors, drops, carrier changes
dmesg -T | grep -i -E "eth|link|nic"
```

## L2 — data link
```
ip link show                     # MTU, state
ip neigh show                    # ARP resolution working?
bridge fdb show
```
Check VLAN assignment and **MTU consistency** here.

## L3 — network
```
ip addr show
ip route get 10.0.5.20           # exact routing decision
ping -c 4 10.0.5.20
mtr -rwc 50 10.0.5.20
```

## L4 — transport
```
nc -zv 10.0.5.20 2049
ss -tulpn
nmap -p 2049,445 10.0.5.20
iptables -L -n -v                # or: nft list ruleset
firewall-cmd --list-all
```

## L7 — application
```
showmount -e 10.0.5.20 ; rpcinfo -p 10.0.5.20
smbclient -L //fb01 -U dylan
dig fb01.corp.local ; dig -x 10.0.5.20
curl -v https://10.0.5.20
klist ; kvno cifs/fb01.corp.local
```

## Host health, in parallel
```
top ; free -h ; vmstat 1
df -h ; df -i ; du -sh /data/*
iostat -xz 1
dmesg -T | tail -50
journalctl -p err -b
```

## Storage path
```
multipath -ll ; lsscsi ; lsblk
nfsstat -m ; nfsstat -c
mount | grep -E "nfs|cifs"
```

## The method itself
1. **What changed?** Nearly every incident follows a change.
2. **What is the scope?** One host or all hosts? One share or all shares? One
   protocol? Scope alone eliminates most hypotheses immediately.
3. **Verify bottom-up.** Do not debate ACLs before confirming the port is open.
4. **Capture evidence before changing anything** — logs, `multipath -ll` output,
   a capture. Once you restart the service, the evidence is gone.
5. **Change one variable at a time**, and write down what you changed.
6. **Confirm the fix and the mechanism.** "It works now" without knowing why
   means it will recur."""),
]


# ----------------------------------------------------------------------------
# Multiple-choice bank
# ----------------------------------------------------------------------------
# t = topic id it belongs to, q = question, o = options, a = index of the
# correct option, why = short explanation shown after answering.

QUIZ = [

# --- Networking fundamentals ------------------------------------------------
dict(t="icmp", q="At which OSI layer does ICMP operate?",
     o=["Layer 2 \u2014 Data Link", "Layer 3 \u2014 Network",
        "Layer 4 \u2014 Transport", "Layer 7 \u2014 Application"], a=1,
     why="ICMP is IP protocol number 1 and rides directly on IP. It has no port numbers, which is why firewall rules for it look different from TCP/UDP rules."),

dict(t="icmp", q="A host does not answer ping, but its web service on 443 responds normally. What is the most likely explanation?",
     o=["The host is down", "ICMP is filtered somewhere in the path",
        "DNS resolution is broken", "The routing table is wrong"], a=1,
     why="ICMP is frequently blocked or rate-limited. A failed ping never proves a host is down \u2014 always test the actual service port."),

dict(t="icmp", q="Blocking ICMP entirely breaks which mechanism, producing a black hole where small packets work and large transfers hang?",
     o=["ARP resolution", "Path MTU Discovery", "TCP retransmission", "DHCP lease renewal"], a=1,
     why="PMTUD relies on ICMP type 3 code 4 (Fragmentation Needed). Without it the sender never learns to reduce packet size, so large transfers stall silently."),

dict(t="traceroute", q="Which ICMP message type makes traceroute work?",
     o=["Echo Reply", "Redirect", "Time Exceeded", "Source Quench"], a=2,
     why="Each router that decrements TTL to zero discards the packet and returns Time Exceeded, which reveals its address."),

dict(t="traceroute", q="Traceroute shows `* * *` at hop 5, but hops 6 through 10 respond normally. What does that mean?",
     o=["Packets are being dropped at hop 5",
        "There is a routing loop at hop 5",
        "Hop 5 simply does not reply to probes",
        "Hop 5 has an MTU mismatch"], a=2,
     why="Traffic clearly passes through hop 5 or later hops could not respond. Many routers deprioritize or suppress ICMP replies for their own control plane."),

dict(t="mtr", q="In mtr output, loss appears at hop 4 but not at the final hop. What is the usual cause?",
     o=["Real packet loss that recovers downstream",
        "ICMP rate limiting on that router",
        "Asymmetric routing", "A duplex mismatch"], a=1,
     why="Only loss that persists to the final hop is real. Intermediate-hop loss that does not carry through is almost always the router deprioritizing ICMP responses."),

dict(t="mtr", q="Why reach for mtr instead of traceroute?",
     o=["It shows the reverse path as well",
        "It runs continuously, so it catches intermittent loss",
        "It works without root privileges",
        "It resolves hostnames more accurately"], a=1,
     why="A single traceroute is one sample. mtr keeps probing, so loss that only occurs a small percentage of the time actually shows up."),

dict(t="netstat", q="Which command is the modern replacement for netstat on Linux?",
     o=["ip", "ss", "lsof", "nmap"], a=1,
     why="ss reads kernel socket data directly and is much faster on busy hosts. netstat is part of the deprecated net-tools package."),

dict(t="netstat", q="`ss -tulpn` shows listening ports on which machine?",
     o=["The local machine only", "Any host on the same subnet",
        "Whichever host you pass as an argument", "All hosts in the ARP table"], a=0,
     why="ss and netstat are local-only. To check a remote host you need nmap or nc, which probe across the network."),

dict(t="tcpudp", q="Which transport protocol does NFSv4 require?",
     o=["UDP", "TCP", "Either, negotiated at mount", "SCTP"], a=1,
     why="NFSv4 mandates TCP. NFSv3 could run over UDP and occasionally still does on legacy systems, which behaves badly on a lossy network."),

dict(t="tcpudp", q="Which of these is NOT provided by TCP?",
     o=["Ordered delivery", "Congestion control",
        "Guaranteed delivery latency", "Retransmission of lost segments"], a=2,
     why="TCP guarantees that data arrives and arrives in order, but makes no promise about how long that takes \u2014 retransmission can make it slower, not faster."),

dict(t="tcpudp", q="What is the correct order of the TCP three-way handshake?",
     o=["SYN \u2192 ACK \u2192 SYN-ACK", "SYN \u2192 SYN-ACK \u2192 ACK",
        "ACK \u2192 SYN \u2192 SYN-ACK", "SYN-ACK \u2192 SYN \u2192 ACK"], a=1,
     why="Client sends SYN, server answers SYN-ACK, client confirms with ACK. In a capture, SYN to SYN-ACK is pure network round-trip time."),

dict(t="ports", q="Which port does LDAPS use?",
     o=["389", "636", "443", "3269"], a=1,
     why="636 is LDAP over SSL/TLS. 389 is plain LDAP and StartTLS; 3269 is the Active Directory global catalog over SSL."),

dict(t="ports", q="Which port does plain LDAP use?",
     o=["88", "389", "445", "636"], a=1,
     why="389 for LDAP, 636 for LDAPS. 88 is Kerberos and 445 is SMB."),

dict(t="ports", q="Which service listens on TCP 2049?",
     o=["iSCSI", "NFS", "SMB", "rpcbind"], a=1,
     why="2049 is NFS. NFSv4 runs entirely over it; NFSv3 also needs rpcbind on 111 plus dynamic ports."),

dict(t="ports", q="Which service listens on TCP 3260?",
     o=["NFS", "SMB", "iSCSI", "Fibre Channel over IP"], a=2,
     why="3260 is the iSCSI target port."),

dict(t="ports", q="Which port does SMB use over TCP on a modern network?",
     o=["139", "389", "445", "3389"], a=2,
     why="445 is SMB over TCP. 139 is the legacy NetBIOS session service; 3389 is RDP."),

dict(t="ports", q="Kerberos authentication traffic uses which port?",
     o=["88", "123", "389", "464"], a=0,
     why="88 is the KDC. 464 is the password-change service, and 123 is NTP \u2014 which Kerberos depends on for clock sync."),

dict(t="subnetting", q="How many usable host addresses does a /26 provide?",
     o=["64", "62", "30", "126"], a=1,
     why="A /26 is 64 addresses, minus the network and broadcast addresses, leaving 62 usable."),

dict(t="subnetting", q="For the network 10.0.5.0/26, what is the broadcast address?",
     o=["10.0.5.63", "10.0.5.64", "10.0.5.127", "10.0.5.255"], a=0,
     why="A /26 block runs .0 through .63. The network address is .0, broadcast is .63, and usable hosts are .1 through .62."),

dict(t="subnetting", q="How many usable addresses does a /29 provide?",
     o=["8", "6", "14", "4"], a=1,
     why="A /29 is 8 addresses, minus network and broadcast, leaving 6."),

dict(t="subnetting", q="Half a customer's hosts can mount an export and half cannot, and the failing hosts are all high in the address range. What should you check first?",
     o=["The export rules on the array", "The subnet mask on the array and the hosts",
        "DNS reverse records", "The NFS version being negotiated"], a=1,
     why="A mask mismatch \u2014 /24 on one side, /25 on the other \u2014 makes the upper half of the range appear off-subnet, which produces exactly this split."),

dict(t="arp", q="What is the purpose of a gratuitous ARP during an array VIP failover?",
     o=["To request the MAC address of the new owner",
        "To announce the new IP-to-MAC binding so switches and hosts update",
        "To verify no duplicate IP exists",
        "To flush the routing table"], a=1,
     why="The new owner announces the binding unsolicited. If gratuitous ARP is filtered, clients keep sending to the old MAC and traffic black-holes until the cache expires."),

dict(t="arp", q="Which command shows the ARP table on a modern Linux system?",
     o=["arp -a", "ip neigh show", "ip route show", "ss -n"], a=1,
     why="`ip neigh show` is the current command. `arp -an` still works where net-tools is installed, but it is deprecated."),

dict(t="gateway", q="What does a default gateway actually do?",
     o=["Translates between dissimilar protocols",
        "Routes packets destined for other networks",
        "Assigns IP addresses to hosts",
        "Resolves hostnames to addresses"], a=1,
     why="A default gateway routes. Protocol translation is the job of a specific protocol gateway, such as an FC-to-iSCSI bridge \u2014 a different device entirely."),

# --- Switching --------------------------------------------------------------
dict(t="l2l3", q="A Layer 2 switch forwards traffic based on what?",
     o=["Destination IP address", "Destination MAC address",
        "Destination port number", "VLAN ID only"], a=1,
     why="Layer 2 builds a MAC address table by learning source MACs per port, and forwards frames to the port matching the destination MAC."),

dict(t="l2l3", q="What is the protocol data unit at Layer 2?",
     o=["Bit", "Frame", "Packet", "Segment"], a=1,
     why="Layer 2 is frames, Layer 3 is packets, Layer 4 is segments (TCP) or datagrams (UDP). Saying a switch forwards packets by MAC mixes two layers."),

dict(t="l2l3", q="What does a Layer 3 switch add over a Layer 2 switch?",
     o=["More ports and higher throughput",
        "Routing between VLANs and subnets in hardware",
        "Support for jumbo frames",
        "Link aggregation"], a=1,
     why="It keeps all Layer 2 behaviour and adds IP routing performed in ASICs rather than software, which is what separates it from a traditional router."),

dict(t="mlag", q="vPC is which vendor's implementation of multi-chassis link aggregation?",
     o=["Arista", "Cisco", "Brocade", "Juniper"], a=1,
     why="vPC is Cisco Nexus. Arista calls it MLAG, Juniper MC-LAG, Dell VLT. Note that VPC also means Virtual Private Cloud in AWS \u2014 unrelated."),

dict(t="mlag", q="What problem does MLAG solve that a standard LACP bundle does not?",
     o=["It increases the maximum frame size",
        "It removes the switch as a single point of failure",
        "It eliminates the need for spanning tree entirely",
        "It allows links of different speeds to be bundled"], a=1,
     why="Standard LAG requires both ends on the same switch. MLAG lets two switches present as one logical peer, so a host or array can dual-home and survive a switch failure."),

dict(t="jumbo", q="Which workload benefits most from jumbo frames?",
     o=["4K random reads", "Large sequential I/O such as backups and replication",
        "DNS queries", "Interactive SSH sessions"], a=1,
     why="The gain comes from fewer per-packet headers and interrupts per gigabyte moved. Small random I/O never fills a 9000-byte frame, so it sees almost no benefit."),

dict(t="jumbo", q="Ping succeeds, the NFS mount succeeds, small operations work, but large file transfers hang. What is the classic cause?",
     o=["The export is read-only",
        "An MTU mismatch somewhere in the path",
        "DNS reverse lookup is failing",
        "The array is out of capacity"], a=1,
     why="That exact signature \u2014 small things fine, large transfers stalled \u2014 is a jumbo frame mismatch black-holing full-size packets when DF is set and ICMP is filtered."),

dict(t="jumbo", q="On Linux, which command tests whether a 9000-byte MTU path actually works end to end?",
     o=["ping -s 9000 10.0.5.20", "ping -M do -s 8972 10.0.5.20",
        "ping -c 9000 10.0.5.20", "ping -f -l 9000 10.0.5.20"], a=1,
     why="8972 payload plus 8 bytes ICMP plus 20 bytes IP equals exactly 9000, and -M do sets Don't Fragment so the packet fails rather than being silently split."),

dict(t="jumbo", q="If hosts are set to MTU 9000, what is a switch typically configured to?",
     o=["9000 exactly", "1500", "9216", "8972"], a=2,
     why="Host MTU counts payload; switches count the whole frame including headers. 9216 is the usual configured value to leave headroom."),

# --- DNS --------------------------------------------------------------------
dict(t="dns", q="Your note described a system that automatically updates records when a device's IP changes. What is that actually describing?",
     o=["DNS itself", "Dynamic DNS (DDNS)", "DHCP", "mDNS"], a=1,
     why="DDNS is one feature layered on DNS. DNS itself is the distributed hierarchical database that resolves names to addresses."),

dict(t="arecord", q="Which record type maps a hostname to an IPv4 address?",
     o=["A", "AAAA", "CNAME", "PTR"], a=0,
     why="A is IPv4 and AAAA is IPv6. CNAME points to another name; PTR is the reverse mapping."),

dict(t="ptrrecord", q="What is the reverse DNS name for 10.0.5.20?",
     o=["10.0.5.20.in-addr.arpa", "20.5.0.10.in-addr.arpa",
        "20.5.0.10.ip6.arpa", "10.0.5.20.reverse.arpa"], a=1,
     why="The octets are reversed and the in-addr.arpa suffix is appended. ip6.arpa is the IPv6 equivalent."),

dict(t="ptrrecord", q="A customer reports NFS mounts that take 30 or more seconds but eventually succeed. What is a likely cause?",
     o=["The array is overloaded", "A missing or wrong PTR record",
        "Jumbo frames are misconfigured", "The export uses the wrong NFS version"], a=1,
     why="The server does a reverse lookup on the client IP. With no PTR, that lookup must time out before the mount proceeds \u2014 slow but ultimately successful."),

dict(t="records", q="Which record type does Active Directory rely on for clients to locate domain controllers?",
     o=["MX", "TXT", "SRV", "NS"], a=2,
     why="SRV records publish service, protocol, port and target. Broken or missing SRV records are the first thing to check when clients cannot find a DC."),

dict(t="dig", q="`dig` returns `status: SERVFAIL`. What does that mean?",
     o=["The name does not exist",
        "The server tried to resolve it and failed",
        "The query timed out at the client",
        "The record exists but has expired"], a=1,
     why="SERVFAIL means a real failure \u2014 broken delegation, DNSSEC validation failure, or an unreachable upstream. NXDOMAIN is the answer for a name that does not exist."),

dict(t="dig", q="Which dig option walks the delegation chain from the root to show exactly where resolution breaks?",
     o=["+short", "+trace", "+tcp", "+noall"], a=1,
     why="+trace is the highest-value option when a name resolves from one server but not another."),

dict(t="dig", q="In a dig response header, what does the `aa` flag indicate?",
     o=["The answer came from cache", "Recursion was available",
        "The answer is authoritative", "The response was truncated"], a=2,
     why="aa means the answer came from a server authoritative for that zone rather than from a cache. ra means recursion available."),

# --- SNMP -------------------------------------------------------------------
dict(t="snmp", q="Which ports does SNMP use for the agent and for traps?",
     o=["161 agent, 162 traps", "162 agent, 161 traps",
        "161 agent, 163 traps", "160 agent, 161 traps"], a=0,
     why="The agent listens on 161 and pushes unsolicited traps to the manager on 162. If 162 is blocked, alerts silently stop arriving."),

dict(t="snmp", q="Which SNMP version adds authentication and encryption?",
     o=["v1", "v2c", "v3", "All versions support it"], a=2,
     why="v1 and v2c both use plaintext community strings. v3 adds user-based security with MD5/SHA authentication and DES/AES encryption."),

dict(t="snmp", q="What is the difference between an SNMP TRAP and an INFORM?",
     o=["INFORM is acknowledged by the manager", "TRAP is encrypted, INFORM is not",
        "INFORM is only in v1", "TRAP carries more data"], a=0,
     why="An INFORM is acknowledged, so the agent knows it arrived. A TRAP is fire-and-forget and can be lost without anyone noticing."),

# --- OSI --------------------------------------------------------------------
dict(t="osi", q="What is the correct name of OSI Layer 3?",
     o=["Networking", "Network", "Internet", "Routing"], a=1,
     why="The layer is Network. 'Internet' is the equivalent layer in the TCP/IP model, which is a separate four-layer model."),

dict(t="osi", q="XDR, which NFS uses to encode data in a platform-neutral way, belongs to which layer?",
     o=["Transport", "Session", "Presentation", "Application"], a=2,
     why="Presentation handles data representation \u2014 encoding, character sets, serialization, compression."),

dict(t="osi", q="VLAN tagging with 802.1Q happens at which layer?",
     o=["Physical", "Data Link", "Network", "Transport"], a=1,
     why="802.1Q inserts a tag into the Ethernet frame header, which is Layer 2."),

dict(t="osi", q="A firewall blocking TCP 2049 is a problem at which layer?",
     o=["Layer 2", "Layer 3", "Layer 4", "Layer 7"], a=2,
     why="Port numbers live in the Transport layer. Naming the layer you have proven good is how you narrow a problem and hand it off cleanly."),

# --- SAN --------------------------------------------------------------------
dict(t="zoning", q="Where is zoning enforced?",
     o=["On the storage array", "In the fabric switch",
        "On the host HBA", "In the multipath driver"], a=1,
     why="Zoning is a fabric function controlling which devices can communicate at all. LUN masking is the array-side control over which LUNs an initiator can see."),

dict(t="lunmasking", q="Where is LUN masking enforced?",
     o=["In the fabric switch", "On the storage array",
        "In the host operating system", "On the SFP"], a=1,
     why="The array binds volumes to a host object built from that host's WWPNs or IQNs, deciding which LUNs that initiator is shown."),

dict(t="lunmasking", q="What happens if you configure zoning but no LUN masking?",
     o=["Nothing \u2014 zoning is sufficient on its own",
        "Every zoned host can see every LUN on the array",
        "The fabric refuses the login",
        "Multipathing fails to build device maps"], a=1,
     why="That is exactly how two unrelated hosts end up writing to the same volume and corrupting the filesystem. It is the reason masking exists."),

dict(t="zoning", q="How is hard zoning enforced?",
     o=["By the fabric name server withholding device information",
        "In the switch ASIC, on a frame-by-frame basis",
        "By the array rejecting unauthorized initiators",
        "By the HBA firmware"], a=1,
     why="Hard zoning drops out-of-zone frames in hardware. Soft zoning only limits what the name server tells an initiator, so a device that already knows an FCID can still reach it."),

dict(t="zoning", q="Which statement about zoning is correct?",
     o=["Hard zoning always means port zoning and soft zoning always means WWN zoning",
        "Membership and enforcement are independent \u2014 WWPN zoning can be hard-enforced",
        "Soft zoning is more secure because it hides devices",
        "Hard zoning cannot be used with WWPNs"], a=1,
     why="This is the common trap. Membership can be by port or by WWPN; enforcement is hard or soft. Modern Brocade and Cisco switches hard-enforce WWPN zoning."),

dict(t="zoning", q="What is the recommended zoning practice, and why?",
     o=["Large zones, to reduce configuration effort",
        "Single-initiator / single-target, to minimise RSCN disruption",
        "One zone per fabric, for simplicity",
        "Zone by node name rather than port name"], a=1,
     why="With small zones, a device joining or leaving only generates RSCNs for genuinely affected devices instead of disrupting every member of a large zone."),

dict(t="wwn", q="Zoning and LUN masking are configured using which identifier?",
     o=["WWNN", "WWPN", "FCID", "The switch domain ID"], a=1,
     why="WWPN identifies a single port. Zoning by node name would expose every port on the device at once."),

dict(t="wwn", q="What is the relationship between WWNN and WWPN?",
     o=["They are the same value in different formats",
        "One WWNN maps to multiple WWPNs",
        "One WWPN maps to multiple WWNNs",
        "WWNN applies to arrays only, WWPN to hosts only"], a=1,
     why="The node name identifies the device as a whole \u2014 an HBA card or an array. Each port on it has its own port name."),

dict(t="wwn", q="What is the iSCSI equivalent of a WWPN?",
     o=["The MAC address", "The IQN", "The target portal group tag", "The FCID"], a=1,
     why="An IQN such as iqn.1994-05.com.redhat:host1abc plays the same role \u2014 it is what you configure access control against."),

dict(t="lun", q="A host is presented one volume over four paths. How many block devices does Linux initially discover?",
     o=["One", "Two", "Four", "It depends on the LUN ID"], a=2,
     why="The host discovers one SCSI device per path. Device-mapper-multipath then coalesces them into a single usable device."),

dict(t="lun", q="A host sees a new volume on only two of its four paths. Where do you look first?",
     o=["The filesystem type", "Zoning and the state of the other two ports",
        "The multipath configuration file", "The host's DNS settings"], a=1,
     why="Partial path visibility points at the fabric or a dead port, not the array. Check FLOGI and the zoning for the missing initiator-target pairs."),

dict(t="sancomponents", q="Dirty or mismatched SFP optics most commonly produce which symptom?",
     o=["Slow but stable throughput", "CRC errors and link flapping",
        "LUN masking failures", "Multipath device naming conflicts"], a=1,
     why="Optical problems show up as physical-layer errors. Check the switch's transceiver output and error counters before suspecting anything higher up."),

dict(t="sancomponents", q="What is standard practice for SAN fabric design?",
     o=["One large fabric for simpler management",
        "Two completely independent fabrics that are never merged",
        "Two fabrics joined by an inter-switch link",
        "One fabric per storage array"], a=1,
     why="Fabric A and Fabric B stay separate so a fabric-wide event \u2014 a bad zone commit, a broadcast storm \u2014 cannot take out both paths at once."),

dict(t="sancomponents", q="Which command shows which devices have logged into a Cisco MDS fabric?",
     o=["show zoneset active", "show flogi database",
        "show interface transceiver", "show vsan membership"], a=1,
     why="FLOGI is fabric login. If an initiator is not in that database it never reached the fabric, so zoning and masking are not yet the problem."),

# --- File protocols ---------------------------------------------------------
dict(t="rpc", q="NFSv3 registers its services with rpcbind on which port?",
     o=["111", "2049", "635", "4045"], a=0,
     why="Clients ask rpcbind on 111 which dynamic ports mountd, statd and nlockmgr are using. That indirection is why NFSv3 through a firewall is painful."),

dict(t="rpc", q="What is the main operational advantage of NFSv4 over NFSv3?",
     o=["It is faster on every workload",
        "Everything runs over port 2049, with no rpcbind or dynamic ports",
        "It does not require authentication",
        "It supports larger files"], a=1,
     why="One port means one firewall rule. v4 also folds locking, ACLs and delegations into the protocol instead of side protocols."),

dict(t="nfsmount", q="Which NFS mount option retries indefinitely and is the correct choice for real data?",
     o=["soft", "hard", "intr", "bg"], a=1,
     why="hard retries until the server responds. soft returns an I/O error that applications frequently ignore, which risks silent corruption."),

dict(t="nfsmount", q="Which command shows the NFS mount options actually negotiated, rather than what you requested?",
     o=["mount | grep nfs", "nfsstat -m", "findmnt -t nfs", "showmount -e"], a=1,
     why="nfsstat -m shows the effective options, including rsize and wsize the server may have negotiated down from what you asked for."),

dict(t="nfsmount", q="What does the mount option `sec=krb5p` provide?",
     o=["Authentication only", "Authentication and integrity",
        "Authentication, integrity and encryption", "Encryption only"], a=2,
     why="krb5 is authentication, krb5i adds integrity checking, krb5p adds privacy \u2014 that is, encryption of the payload."),

dict(t="nfssmb", q="How do NFS and SMB differ on case sensitivity?",
     o=["Both are case-sensitive",
        "NFS is case-sensitive; SMB is case-insensitive but case-preserving",
        "NFS is case-insensitive; SMB is case-sensitive",
        "Both are case-insensitive"], a=1,
     why="This bites hardest in multiprotocol exports, where a file created over one protocol may be unreachable or duplicated over the other."),

dict(t="nfssmb", q="Which SMB dialect should never be used?",
     o=["SMB1", "SMB2.0.2", "SMB3.0", "SMB3.1.1"], a=0,
     why="SMB1 is deprecated and insecure. Seeing it in a capture at all is a red flag worth raising."),

dict(t="s3", q="Which statement about S3 objects is correct?",
     o=["They can be modified in place at any byte offset",
        "They are immutable \u2014 you replace rather than edit them",
        "They support POSIX file locking",
        "They can be renamed atomically"], a=1,
     why="No in-place partial writes and no POSIX semantics. That is the fundamental trade for scale, rich metadata and HTTP-native access."),

dict(t="s3", q="S3 buckets organise data how?",
     o=["As a directory tree, like a filesystem",
        "As a flat namespace where prefixes simulate folders",
        "As a block device exposed over HTTP",
        "As a relational table indexed by key"], a=1,
     why="There are no real directories. Prefixes and delimiters make listings look hierarchical, which is why listing a deep 'folder' is a prefix scan."),

dict(t="s3req", q="A customer gets 403 SignatureDoesNotMatch on every S3 request. What do you check first?",
     o=["Bucket policy", "Clock skew on the client",
        "Whether the bucket exists", "The object's storage class"], a=1,
     why="SigV4 signatures cover a timestamp. A client whose clock has drifted produces signatures the server rejects, no matter how correct the keys are."),

dict(t="s3req", q="Which AWS CLI command set maps one-to-one onto the underlying API calls?",
     o=["aws s3", "aws s3api", "aws s3control", "aws configure"], a=1,
     why="`aws s3` is the friendly high-level set. `aws s3api` is what you want when reproducing a customer's exact request or inspecting a raw response."),

# --- Permissions ------------------------------------------------------------
dict(t="posix", q="What do the permissions `-rwxr-xr-x` correspond to numerically?",
     o=["644", "755", "775", "700"], a=1,
     why="Owner rwx is 7, group r-x is 5, other r-x is 5."),

dict(t="posix", q="On a directory, what does the execute bit actually permit?",
     o=["Running scripts stored in it",
        "Traversing into it and stat-ing its contents",
        "Listing the filenames inside it",
        "Creating new files inside it"], a=1,
     why="Read lists names, write creates and deletes entries, execute traverses. You need execute on every parent directory in a path to reach a file."),

dict(t="posix", q="Deleting a file depends on write permission on what?",
     o=["The file itself", "The directory containing it",
        "Both the file and the directory", "The filesystem mount point"], a=1,
     why="Removing a directory entry is a modification of the directory. This is exactly why the sticky bit exists for shared directories."),

dict(t="acl", q="A `+` at the end of the permissions in `ls -l` output means what?",
     o=["The file is a symlink", "An ACL is present beyond the mode bits",
        "The file has extended attributes", "The file is immutable"], a=1,
     why="If permissions look correct but access is denied, that plus sign is the first thing to notice. A `.` in that position indicates an SELinux context."),

dict(t="sticky", q="What does the sticky bit do on a shared directory?",
     o=["Prevents any file from being deleted",
        "Restricts deletion and renaming to the file's owner, the directory owner, or root",
        "Makes new files inherit the directory's group",
        "Forces all files to be created read-only"], a=1,
     why="It is what makes a world-writable /tmp safe \u2014 everyone can create files, but nobody can remove anyone else's."),

dict(t="sticky", q="In `drwxrwxrwt`, what does the trailing `t` indicate?",
     o=["A temporary filesystem", "The sticky bit is set",
        "The directory is a mount point", "Text mode is enabled"], a=1,
     why="A capital T instead means the sticky bit is set without the other-execute bit \u2014 usually a mistake."),

dict(t="setuid", q="What does setgid on a *directory* do?",
     o=["Runs programs in it as the directory's group",
        "Makes new files and subdirectories inherit the directory's group",
        "Prevents group members from deleting files",
        "Grants the group root privileges"], a=1,
     why="This is the standard way to build a shared group workspace \u2014 everything created stays owned by the project group rather than the creator's primary group."),

dict(t="setuid", q="Why is /usr/bin/passwd setuid root?",
     o=["So it runs faster",
        "So an ordinary user can update /etc/shadow, which they cannot read",
        "So it can be executed by any user",
        "So it survives a filesystem remount"], a=1,
     why="setuid makes the process run with the file owner's effective UID. It is also why setuid-root binaries are a major privilege-escalation surface worth auditing."),

dict(t="setuid", q="A setuid binary works locally but does nothing over NFS. What is the likely reason?",
     o=["NFS does not support execute permission",
        "The export is mounted nosuid",
        "The UID does not exist on the server",
        "NFSv4 removed setuid support"], a=1,
     why="nosuid is commonly set on NFS exports precisely to stop setuid binaries crossing the mount."),

dict(t="netgroup", q="What is the structure of a netgroup entry?",
     o=["(user, group, domain)", "(host, user, domain)",
        "(host, IP, netmask)", "(user, uid, gid)"], a=1,
     why="A dash in any field is a wildcard-none. Netgroups are referenced with an @ prefix in places like /etc/exports."),

dict(t="netgroup", q="An NFS export rule using `@engineering` is not matching a client that should be a member. What do you check first?",
     o=["The client's /etc/exports",
        "`getent netgroup engineering` on the NFS server",
        "The client's DNS settings",
        "The array's LUN masking"], a=1,
     why="If the server cannot resolve the netgroup, the rule can never match no matter what the directory contains. Resolution depends on nsswitch and the backend."),

# --- Kerberos, AD, LDAP -----------------------------------------------------
dict(t="kerberos", q="Which two services make up the Kerberos KDC?",
     o=["AS and TGS", "AS and SPN", "TGT and TGS", "KDC and PAC"], a=0,
     why="The Authentication Service issues the TGT; the Ticket Granting Service issues service tickets. TGT is a ticket, not a service."),

dict(t="kerberos", q="A Kerberos service ticket is encrypted with whose key?",
     o=["The user's key", "The krbtgt account's key",
        "The service account's key", "The KDC's master key"], a=2,
     why="That is why the service can validate the ticket itself without ever contacting the KDC \u2014 it already holds the key needed to decrypt it."),

dict(t="kerberos", q="Kerberos governs which of the following?",
     o=["Authorization \u2014 what data you may access",
        "Authentication \u2014 proving who you are",
        "Both equally",
        "Neither; it only encrypts traffic"], a=1,
     why="If Kerberos fails, access fails regardless of correct permissions. But if it succeeds and you still get access denied, stop looking at Kerberos \u2014 it is the ACL."),

dict(t="kerberos", q="Beyond how much clock skew does Kerberos authentication fail by default?",
     o=["30 seconds", "5 minutes", "15 minutes", "1 hour"], a=1,
     why="Tickets carry timestamps, so time sync is a hard dependency. Check NTP before anything else on a Kerberos case."),

dict(t="kerberos", q="A packet capture shows SMB falling back to NTLM where you expected Kerberos. What does that suggest?",
     o=["The client is running an old SMB dialect",
        "Kerberos broke \u2014 likely SPN, DNS, or time",
        "The share is configured for guest access",
        "Signing is disabled on the server"], a=1,
     why="This is the single most valuable thing to spot in an SMB capture. The client tried Kerberos, could not get a usable ticket, and silently downgraded."),

dict(t="spn", q="What is the correct format of a Service Principal Name?",
     o=["hostname/service", "service/hostname",
        "DOMAIN\\service", "service@REALM"], a=1,
     why="For example cifs/fb01.corp.local. The client builds it from the hostname it connected to, which is why connecting by an unregistered alias breaks Kerberos."),

dict(t="spn", q="What happens when the same SPN is registered on two different accounts?",
     o=["The first account registered wins",
        "Kerberos fails for both",
        "The KDC picks one at random per request",
        "Nothing \u2014 duplicates are allowed"], a=1,
     why="A top-tier AD problem, and easy to create by rejoining a machine to the domain. `setspn -X` finds duplicates across the forest."),

dict(t="spn", q="Why does connecting to \\\\10.0.5.20\\share behave differently from \\\\fb01.corp.local\\share?",
     o=["IP connections use a different SMB dialect",
        "Connecting by IP generally cannot use Kerberos at all",
        "IP connections bypass the firewall",
        "The array only publishes shares by name"], a=1,
     why="The client builds the SPN from the name it used. An IP address is not a registered SPN, so it falls back to NTLM or fails outright."),

dict(t="ad", q="What is an Active Directory forest a boundary for?",
     o=["Replication only", "Security and schema",
        "Group Policy only", "DNS zones only"], a=1,
     why="The forest is the top-level security and schema boundary. The domain is the replication and policy boundary beneath it."),

dict(t="ad", q="A domain join keeps failing. Which three things account for nearly all such cases?",
     o=["Firewall, licensing, disk space",
        "DNS, time sync, and the computer account or SPN",
        "NTFS permissions, share permissions, and quotas",
        "Cabling, VLAN, and MTU"], a=1,
     why="Check them in that order. Every one of them will produce a failure that looks like an authentication problem."),

dict(t="ldap", q="What does the LDAP filter `(&(objectClass=user)(sAMAccountName=dylan))` do?",
     o=["Matches entries that are users OR named dylan",
        "Matches entries that are users AND named dylan",
        "Matches all users, excluding dylan",
        "Matches the user dylan in any object class"], a=1,
     why="LDAP filters use prefix notation: & is AND, | is OR, ! is NOT, with each condition in its own parentheses."),

dict(t="ldap", q="On Linux, which file wires LDAP into user and group lookup?",
     o=["/etc/ldap.conf", "/etc/nsswitch.conf",
        "/etc/krb5.conf", "/etc/sssd/sssd.conf"], a=1,
     why="nsswitch decides which sources are consulted for passwd and group. It is why `id dylan` can return a UID that came from the directory."),

dict(t="ldap", q="Which statement best describes the relationship between AD and LDAP?",
     o=["They are the same thing",
        "AD speaks LDAP, but is also Kerberos, DNS and Group Policy",
        "LDAP is Microsoft's implementation of AD",
        "AD replaced LDAP"], a=1,
     why="LDAP is the query protocol. AD is a full platform built around it. OpenLDAP and 389 Directory Server are pure LDAP directories with no Kerberos or GPO layer."),

# --- Linux ------------------------------------------------------------------
dict(t="ls", q="Which `ls` flag shows hidden dotfiles?",
     o=["-I", "-a", "-l", "-h"], a=1,
     why="Lowercase -a includes hidden files. Capital -I is --ignore=PATTERN, which excludes files \u2014 the exact opposite."),

dict(t="ls", q="What does `ls -ltr` give you, and why is it useful in a log directory?",
     o=["Long listing, sorted by size, largest first",
        "Long listing, sorted by time, newest last",
        "Long listing, recursive, in reverse alphabetical order",
        "Long listing with inode numbers"], a=1,
     why="Oldest first means the newest file lands at the bottom, right above your prompt \u2014 no scrolling required."),

dict(t="tail", q="Which tail option keeps following a log across a logrotate?",
     o=["-f", "-F", "-n", "--retry only"], a=1,
     why="-f follows the file descriptor and goes silent once the file is renamed. -F follows the name and reopens it \u2014 the fix for 'I left it running overnight and got nothing'."),

dict(t="countlogs", q="What does `grep -c pattern file` actually count?",
     o=["Every occurrence of the pattern",
        "Lines containing at least one match",
        "Characters matched",
        "Files containing a match"], a=1,
     why="If a message can appear twice on one line, -c undercounts. Use `grep -o pattern file | wc -l` to count occurrences."),

dict(t="countlogs", q="Which pipeline turns a noisy log into a ranked list of distinct messages?",
     o=["sort | uniq | wc -l", "sort | uniq -c | sort -rn",
        "uniq -c | sort | head", "grep -c | sort -n"], a=1,
     why="uniq -c requires sorted input, then the numeric reverse sort ranks by frequency. It is the single most reusable pipeline in log analysis."),

dict(t="rollinglogs", q="Why use `zgrep` rather than `grep` across `/var/log/messages*`?",
     o=["It is faster on large files",
        "It handles both compressed and uncompressed files in one pass",
        "It searches recursively by default",
        "It preserves timestamps in the output"], a=1,
     why="zgrep transparently handles the .gz rotations and plain files together, so one command covers the whole retention window."),

dict(t="rollinglogs", q="Why does `ls -tr /var/log/messages* | xargs zgrep -Hi error` beat a plain glob?",
     o=["It avoids the argument length limit",
        "It puts the output in chronological order",
        "It skips compressed files",
        "It deduplicates matching lines"], a=1,
     why="Shell glob expansion sorts messages.1 before messages.10, which is not time order. Sorting by mtime makes the output read forward in time."),

dict(t="ps", q="A process is stuck in `D` state. What does that mean?",
     o=["It is a daemon",
        "It is in uninterruptible sleep inside a kernel I/O call",
        "It has been stopped by a signal",
        "It is a defunct zombie"], a=1,
     why="You cannot kill it, not even with -9. Several processes in D on the same mount usually means a hung NFS mount or a dead storage path."),

dict(t="watch", q="What does the `-d` flag add to `watch`?",
     o=["Runs the command as a daemon",
        "Highlights the characters that changed since the last refresh",
        "Doubles the refresh interval",
        "Writes output to a file"], a=1,
     why="It turns watch from output scrolling past into an actual change detector \u2014 ideal for interface error counters or a flapping multipath."),

dict(t="systemctl", q="Which command is required after editing a systemd unit file?",
     o=["systemctl restart <unit>", "systemctl reload <unit>",
        "systemctl daemon-reload", "systemctl reset-failed"], a=2,
     why="Without it, systemd keeps running the old definition and your change appears to have had no effect."),

dict(t="journalctl", q="What does `journalctl -p warning` return?",
     o=["Warnings only",
        "Warnings and everything more severe",
        "Warnings and everything less severe",
        "Warnings from the previous boot"], a=1,
     why="The -p filter is inclusive of higher severity, so you get warning, err, crit, alert and emerg \u2014 normally what you want."),

dict(t="sed", q="What does `sed -n '/09:00/,/10:00/p' /var/log/messages` do?",
     o=["Deletes lines between the two patterns",
        "Prints lines between the two matching patterns",
        "Replaces the first pattern with the second",
        "Prints only lines matching both patterns"], a=1,
     why="The /start/,/end/ range form is the fastest way to carve a time window out of a flat log file."),

dict(t="tcpdump", q="What does `-s 0` do in tcpdump?",
     o=["Captures zero packets \u2014 a dry run",
        "Captures the full packet rather than truncating",
        "Disables name resolution",
        "Sets the snapshot file size to unlimited"], a=1,
     why="Older versions truncated by default, losing payload you later need. -nn is what disables name and port resolution."),

dict(t="tcpdump", q="Which options bound a tcpdump capture so it cannot fill the disk?",
     o=["-v and -A", "-C and -W", "-s and -i", "-e and -x"], a=1,
     why="-C sets file size in MB and -W the number of files to rotate through. On a busy array-facing interface an unbounded capture will do real damage."),

dict(t="ss", q="Which ss flag exposes per-connection RTT, congestion window and retransmit counts?",
     o=["-s", "-ti", "-tulpn", "-m"], a=1,
     why="When a customer says 'the network is slow', retransmits and RTT on the actual storage connection are hard evidence \u2014 no packet capture required."),

dict(t="openports", q="Which tool checks whether a port is open on a REMOTE host?",
     o=["netstat", "ss", "nmap", "lsof"], a=2,
     why="netstat, ss and lsof are all local-only. nmap and nc probe across the network."),

dict(t="openports", q="What does `nmap -Pn` do?",
     o=["Scans only privileged ports",
        "Skips host discovery, for hosts that block ping",
        "Performs a passive scan",
        "Disables port randomisation"], a=1,
     why="Without it, nmap gives up on hosts that do not answer ping \u2014 which includes plenty of hardened systems that are perfectly reachable on their service ports."),

dict(t="ipcmds", q="Why prefer `ip addr` over `ifconfig` on modern Linux?",
     o=["ifconfig is slower",
        "ifconfig does not show secondary addresses and is often not installed",
        "ifconfig cannot show the MTU",
        "ifconfig requires root"], a=1,
     why="net-tools is deprecated and absent from many minimal and container images. A host can have an address that ip addr shows and ifconfig does not."),

# --- Wireshark --------------------------------------------------------------
dict(t="wsnfs", q="Which Wireshark field gives you the NFS server response time?",
     o=["frame.time_delta", "rpc.time", "tcp.analysis.ack_rtt", "nfs.status"], a=1,
     why="Wireshark pairs each RPC Call with its Reply and computes rpc.time. Apply it as a column and sort descending to find the slow operations."),

dict(t="wslatency", q="Where do you measure pure network round-trip time in a capture?",
     o=["Between a request and its response",
        "Between SYN and SYN-ACK in the TCP handshake",
        "From the first to the last frame of the conversation",
        "From the DNS query to its answer"], a=1,
     why="The handshake involves no application processing, so it isolates the network component cleanly."),

dict(t="wslatency", q="A capture shows low rpc.time but the customer reports poor throughput. What does that indicate?",
     o=["The storage array is overloaded",
        "The bottleneck is client-side \u2014 serialisation or small I/O",
        "The network is dropping packets",
        "The capture was taken on the wrong interface"], a=1,
     why="The server is answering quickly. Being able to say that clearly, and prove it, is often the most valuable outcome of the analysis."),

dict(t="wsnfs", q="In NFSv4.1, why can the packet summary mislead you?",
     o=["Operations are encrypted by default",
        "Operations are batched into COMPOUND calls",
        "The protocol uses UDP",
        "Sequence numbers are randomised"], a=1,
     why="One packet carries many operations behind a leading SEQUENCE op. You have to read the operations list inside the COMPOUND."),

dict(t="wssmb", q="During SMB session setup you see STATUS_MORE_PROCESSING_REQUIRED. What does it mean?",
     o=["Authentication failed",
        "It is normal \u2014 part of the NTLM message exchange",
        "The server is overloaded",
        "The dialect negotiation failed"], a=1,
     why="It appears between the NTLMSSP CHALLENGE and AUTH messages. It is an expected intermediate status, not an error."),

dict(t="wssmb", q="In an SMB conversation, which step returns a TreeID?",
     o=["Negotiate Protocol", "Session Setup", "Tree Connect", "Create"], a=2,
     why="Tree Connect attaches to the share. Create then opens a file and returns a FileID \u2014 and is where STATUS_ACCESS_DENIED shows up."),

# --- Windows ----------------------------------------------------------------
dict(t="winevent", q="Event IDs 129 and 153 in the Windows System log relate to what?",
     o=["Failed logons", "Storage path problems \u2014 device reset and I/O retried",
        "Group Policy processing", "Network adapter link changes"], a=1,
     why="They are the classic storage-path complaints. Correlate the timestamps against the array's own logs for the same window."),

dict(t="winevent", q="Which PowerShell cmdlet reads the newer per-component event channels such as SMBClient/Operational?",
     o=["Get-EventLog", "Get-WinEvent", "Get-Event", "Show-EventLog"], a=1,
     why="Get-EventLog is legacy and can only see the classic logs. Get-WinEvent reaches the Applications and Services channels."),

# --- Method -----------------------------------------------------------------
dict(t="troubleshooting", q="What is the most useful first question on a new incident?",
     o=["Which vendor's hardware is it?",
        "What changed?",
        "How many users are affected?",
        "Has it been escalated before?"], a=1,
     why="Nearly every incident follows a change. Scope \u2014 one host or all hosts, one share or all shares \u2014 is the strong second question, because it eliminates most hypotheses immediately."),

dict(t="troubleshooting", q="Why capture evidence before restarting a service?",
     o=["Restarting is rarely effective",
        "The restart destroys the state that explains the fault",
        "It is required by change control",
        "Logs are not written during a restart"], a=1,
     why="'It works now' without knowing why means it will recur, and you will have thrown away the only chance to find out."),

dict(t="ping", q="What does a successful ping actually prove?",
     o=["The host and its services are healthy",
        "Layer 3 reachability, and nothing above it",
        "That DNS is resolving correctly",
        "That the MTU is correct end to end"], a=1,
     why="A host can answer ICMP while the service you care about is dead. Follow up with `nc -zv host port` against the real service."),

dict(t="grep", q="When does `--line-buffered` matter?",
     o=["When searching very large files",
        "When grep sits in a pipe after `tail -f`",
        "When using -r on many directories",
        "When the pattern contains regex metacharacters"], a=1,
     why="Without it, grep buffers its output and matches appear in bursts instead of as they happen — which defeats the point of following a live log."),

dict(t="grep", q="Which grep flag treats the pattern as a literal string rather than a regex?",
     o=["-w", "-F", "-E", "-o"], a=1,
     why="-F is also faster. Useful for phrases containing dots, brackets or parentheses that would otherwise be interpreted."),

dict(t="find", q="Why pair `find -print0` with `xargs -0`?",
     o=["It is faster on large trees",
        "It handles filenames containing spaces correctly",
        "It preserves file permissions",
        "It avoids following symlinks"], a=1,
     why="Null-separation is the only safe delimiter for filenames. Worth defaulting to, since a single space breaks the naive version silently."),

dict(t="logquery", q="Which log message indicates an NFS client is holding a file handle the server no longer recognises?",
     o=["RPC: Timed out", "Stale file handle",
        "Access denied by server", "Connection reset by peer"], a=1,
     why="It usually means the exported filesystem was recreated, remounted, or the export changed underneath a client that still had the old handle cached."),

dict(t="logquery", q="On a systemd host, why prefer journalctl over grepping /var/log/messages?",
     o=["It is the only place errors are recorded",
        "It combines unit, time window and severity filters in one query",
        "It never rotates",
        "It stores logs in plain text"], a=1,
     why="`journalctl -u nfs-server --since \'1 hour ago\' -p warning` replaces a whole grep pipeline. Note the journal may be volatile and lost on reboot."),

dict(t="openfile", q="What is the right way to inspect a multi-gigabyte log on a production host?",
     o=["cat, then scroll back", "vi, and use / to search",
        "less or tail", "grep the whole file into a new file first"], a=2,
     why="cat floods the terminal and vi loads the whole file into memory. less streams it — and its F key follows like tail -f, then Ctrl-C drops you back to browsing."),

dict(t="misccmds", q="`df -h` shows plenty of free space, but writes fail with 'No space left on device'. What do you check next?",
     o=["df -i", "du -sh", "lsof +D", "mount -o remount"], a=0,
     why="Exhausted inodes look exactly like a full disk to an application. Millions of tiny files will do it long before the capacity runs out."),

dict(t="misccmds", q="Which command shows which processes are holding files open under a mount point?",
     o=["ps aux", "lsof +D /mnt/data", "ss -tp", "fuser -a"], a=1,
     why="Essential when a mount will not unmount. `lsof -i :2049` does the equivalent for a port."),
]


# ----------------------------------------------------------------------------
# Derived data: topic numbering, stable question ids, section hints
# ----------------------------------------------------------------------------

_STOP = set("""
the a an and or of to in for on at by with is are was were be been it its this that
these those you your we our as if not but from than then when where which who whom
what how why does do did done can could should would may might must will shall into
over under more most less least other another same such only just also very much many
any all each both few some own so no nor too now use used using via per
""".split())


def _tok(s):
    return {w for w in re.findall(r"[a-z0-9_\-/.]{3,}", s.lower()) if w not in _STOP}


def _sections(answer):
    """[(heading, body)] for each '## ' block in a topic answer."""
    out, head, body = [], None, []
    for line in answer.split("\n"):
        if line.startswith("## "):
            if head is not None:
                out.append((head, "\n".join(body)))
            head, body = line[3:].strip(), []
        elif head is not None:
            body.append(line)
    if head is not None:
        out.append((head, "\n".join(body)))
    return out


def _locate_section(item, topic):
    """Best-guess section of the topic that covers this question, or None.

    Deliberately conservative: a heading match is worth more than a body match,
    and an ambiguous winner falls back to None so the pointer stays topic-level
    rather than confidently wrong.
    """
    secs = _sections(topic["a"])
    if len(secs) < 2:
        return None
    want = _tok(item["q"] + " " + item["why"])
    scored = sorted(
        ((3 * len(want & _tok(h)) + len(want & _tok(b)), h) for h, b in secs),
        reverse=True)
    if scored[0][0] >= 4 and scored[0][0] >= scored[1][0] + 2:
        return scored[0][1]
    return None


def _prepare():
    for n, t in enumerate(TOPICS, 1):
        t["n"] = n
    by, taken = {t["id"]: t for t in TOPICS}, set()
    for q in QUIZ:
        qid = hashlib.sha1(q["q"].encode("utf-8")).hexdigest()[:10]
        while qid in taken:                     # ids must never collide
            qid = hashlib.sha1((qid + q["q"]).encode("utf-8")).hexdigest()[:10]
        taken.add(qid)
        q["id"] = qid
        t = by.get(q["t"])
        q["sec"] = _locate_section(q, t) if t else None


_prepare()


# ----------------------------------------------------------------------------
# Theme — dark "liquid glass": aurora backdrop, frosted surface, cyan signal
# ----------------------------------------------------------------------------

class Theme:
    # Aurora backdrop blobs: (x, y, radius, (r, g, b))
    BASE_RGB = (9, 15, 26)
    BLOBS = [
        (0.14, 0.10, 0.62, (20, 66, 88)),      # teal
        (0.88, 0.22, 0.58, (48, 28, 82)),      # violet
        (0.74, 0.90, 0.54, (12, 78, 86)),      # cyan
        (0.28, 0.78, 0.52, (24, 42, 96)),      # indigo
    ]

    GLASS = "#151F2B"          # frosted surface
    GLASS_HI = "#1D2937"       # raised elements
    GLASS_LO = "#101925"       # recessed elements
    INK = "#E6EEF4"
    MUTED = "#93A7B7"
    FAINT = "#5F7385"
    LINE = "#26333F"           # hairline separators
    EDGE = "#3B4C5C"           # specular edge
    ACCENT = "#5AD2E6"
    ACCENT_DIM = "#1B3D48"
    GOOD = "#4ECF9E"
    BAD = "#F2836F"
    GOOD_DIM = "#12332A"
    BAD_DIM = "#39201B"
    FLAG = "#FFC86B"
    FLAG_DIM = "#3A2E15"
    CODE_BG = "#0D1620"
    CODE_FG = "#9FD4E6"

    MARGIN = 16                # window edge -> glass surface
    INSET = 15                 # glass surface -> content
    RADIUS = 22

    def __init__(self, root):
        fams = set(tkfont.families(root))

        def pick(cands, fallback):
            for c in cands:
                if c in fams:
                    return c
            return fallback

        ui = pick(["Inter", "SF Pro Text", "Helvetica Neue", "Segoe UI",
                   "DejaVu Sans", "Arial"], "TkDefaultFont")
        mono = pick(["JetBrains Mono", "SF Mono", "Menlo", "Consolas",
                     "DejaVu Sans Mono", "Courier New"], "TkFixedFont")
        self.ui_family, self.mono_family = ui, mono

        self.title = (ui, 15, "bold")
        self.h2 = (ui, 12, "bold")
        self.body = (ui, 11)
        self.body_bold = (ui, 11, "bold")
        self.small = (ui, 10)
        self.question = (ui, 15)
        self.mono_small = (mono, 9)
        self.eyebrow = (mono, 9, "bold")
        self.chrome = (mono, 9)


# ----------------------------------------------------------------------------
# Aurora backdrop
# ----------------------------------------------------------------------------

def make_aurora(w, h, th, scale=5):
    """Soft mesh gradient rendered small, then zoomed — the upscale is the blur."""
    sw, sh = max(4, w // scale), max(4, h // scale)
    img = tk.PhotoImage(width=sw, height=sh)
    br, bg_, bb = th.BASE_RGB
    rows = []
    for yi in range(sh):
        v = yi / sh
        row = []
        for xi in range(sw):
            u = xi / sw
            r, g, b = br, bg_, bb
            for cx, cy, rad, (cr, cg, cb) in th.BLOBS:
                dx, dy = (u - cx), (v - cy) * 0.85
                t = math.exp(-(dx * dx + dy * dy) / (rad * rad * 0.42))
                r += (cr - br) * t
                g += (cg - bg_) * t
                b += (cb - bb) * t
            row.append("#%02x%02x%02x" % (min(255, int(r)), min(255, int(g)),
                                          min(255, int(b))))
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    return img.zoom(scale)


def rounded_rect(cv, x, y, w, h, r, **kw):
    """Rounded rectangle as a polygon — crisper than smooth=True."""
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, 0.0), (x + r, y + r, 90.0),
                       (x + r, y + h - r, 180.0), (x + w - r, y + h - r, 270.0)):
        for k in range(9):
            a = math.radians(a0 + k * 90.0 / 8.0)
            pts += [cx + r * math.cos(a), cy - r * math.sin(a)]
    return cv.create_polygon(pts, **kw)


# ----------------------------------------------------------------------------
# Scrolling
# ----------------------------------------------------------------------------

def wheel_units(e):
    """Normalise wheel deltas across macOS, Windows and X11."""
    num = getattr(e, "num", 0)
    if num == 4:
        return -3
    if num == 5:
        return 3
    d = getattr(e, "delta", 0)
    if d == 0:
        return 0
    if abs(d) >= 120:                 # Windows: multiples of 120
        return int(-d / 120) * 3
    return max(-25, min(25, int(-d * 2) or (-1 if d > 0 else 1)))   # macOS


class GlassScroll(tk.Canvas):
    """Slim frameless scrollbar."""

    W = 6

    def __init__(self, master, th, command, bg=None):
        super().__init__(master, width=self.W, bg=bg or th.GLASS,
                         highlightthickness=0, bd=0)
        self.th, self.command = th, command
        self.first, self.last = 0.0, 1.0
        self._grab = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_grab", None))

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._draw()

    def _draw(self):
        self.delete("all")
        h = self.winfo_height()
        if h <= 1 or (self.last - self.first) >= 0.999:
            return
        y0, y1 = self.first * h, self.last * h
        if y1 - y0 < 22:
            y1 = min(h, y0 + 22)
            y0 = y1 - 22
        self.create_rectangle(1, y0 + 1, self.W - 1, y1 - 1,
                              fill=self.th.EDGE, outline="")

    def _frac(self, y):
        h = max(1, self.winfo_height())
        span = self.last - self.first
        return max(0.0, min(1.0 - span, y / h - span / 2))

    def _press(self, e):
        self._grab = True
        self.command("moveto", self._frac(e.y))

    def _drag(self, e):
        if self._grab:
            self.command("moveto", self._frac(e.y))


class ScrollArea(tk.Frame):
    """Canvas-backed scrollable container exposing .inner and .scroll_by()."""

    def __init__(self, master, th, bg=None, **kw):
        bg = bg or th.GLASS
        super().__init__(master, bg=bg, **kw)
        self.th = th
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = GlassScroll(self, th, self.canvas.yview, bg=bg)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y", padx=(2, 2))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))

    def scroll_by(self, units):
        self.canvas.yview_scroll(units, "units")


# ----------------------------------------------------------------------------
# Markup rendering
# ----------------------------------------------------------------------------

_INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*`\n]+\*)")


def setup_text_tags(txt, th):
    txt.tag_configure("h", font=th.h2, foreground=th.INK, spacing1=16,
                      spacing3=5)
    txt.tag_configure("body", font=th.body, foreground=th.INK, spacing1=1,
                      spacing3=7)
    txt.tag_configure("bullet", font=th.body, foreground=th.INK, spacing3=4,
                      lmargin1=14, lmargin2=30)
    txt.tag_configure("code", font=th.mono_small, foreground=th.CODE_FG,
                      background=th.CODE_BG, lmargin1=14, lmargin2=14,
                      rmargin=14, spacing1=1, spacing3=1)
    txt.tag_configure("bold", font=th.body_bold, foreground="#FFFFFF")
    txt.tag_configure("italic", font=(th.ui_family, 11, "italic"))
    txt.tag_configure("kbd", font=th.mono_small, background=th.CODE_BG,
                      foreground=th.CODE_FG)
    txt.tag_configure("blank", font=(th.ui_family, 4))


def _insert_inline(txt, line, base):
    for part in _INLINE.split(line):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            txt.insert("end", part[2:-2], (base, "bold"))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            txt.insert("end", part[1:-1], (base, "kbd"))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            txt.insert("end", part[1:-1], (base, "italic"))
        else:
            txt.insert("end", part, (base,))


def _flush_code(txt, buf):
    while buf and not buf[0].strip():
        buf.pop(0)
    while buf and not buf[-1].strip():
        buf.pop()
    if not buf:
        return
    width = max(len(x) for x in buf) + 2
    for x in buf:
        txt.insert("end", "  " + x.ljust(width) + "\n", ("code",))
    buf.clear()


def render_markup(txt, content):
    """Render light markup. Wrapped source lines are rejoined into paragraphs
    so the Text widget can reflow them, and so inline spans may cross lines."""
    txt.configure(state="normal")
    txt.delete("1.0", "end")
    in_code, buf, para, items = False, [], [], []

    def flush_para():
        if para:
            _insert_inline(txt, " ".join(para), "body")
            txt.insert("end", "\n")
            del para[:]

    def flush_items():
        for it in items:
            txt.insert("end", "\u2022   ", ("bullet",))
            _insert_inline(txt, it, "bullet")
            txt.insert("end", "\n")
        del items[:]

    def flush_all():
        flush_para()
        flush_items()

    for line in content.split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                _flush_code(txt, buf)
            else:
                flush_all()
            in_code = not in_code
            txt.insert("end", " \n", ("blank",))
            continue
        if in_code:
            buf.append(line)
        elif line.startswith("## "):
            flush_all()
            _insert_inline(txt, line[3:], "h")
            txt.insert("end", "\n")
        elif line.startswith("- "):
            flush_para()
            items.append(line[2:])
        elif line.startswith("  ") and line.strip() and items:
            items[-1] += " " + line.strip()
        elif not line.strip():
            flush_all()
            txt.insert("end", " \n", ("blank",))
        else:
            flush_items()
            para.append(line)
    if in_code:
        _flush_code(txt, buf)
    flush_all()
    txt.configure(state="disabled")
    txt.yview_moveto(0.0)


class ContentPane(tk.Frame):
    MAX_COL = 830

    def __init__(self, master, th, padx=32, pady=24, bg=None):
        bg = bg or th.GLASS
        super().__init__(master, bg=bg)
        self.th, self._padx = th, padx
        self.txt = tk.Text(self, wrap="word", bd=0, highlightthickness=0,
                           bg=bg, fg=th.INK, padx=padx, pady=pady,
                           cursor="arrow", insertwidth=0,
                           selectbackground=th.ACCENT_DIM,
                           selectforeground=th.INK)
        self.bar = GlassScroll(self, th, self.txt.yview, bg=bg)
        self.txt.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y", padx=(2, 2))
        self.txt.pack(side="left", fill="both", expand=True)
        setup_text_tags(self.txt, th)
        self.txt.configure(state="disabled")
        self.bind("<Configure>", self._resize)

    def _resize(self, e):
        rm = max(0, e.width - self._padx * 2 - self.MAX_COL)
        for tag in ("body", "bullet", "h"):
            self.txt.tag_configure(tag, rmargin=rm)
        self.txt.tag_configure("code", rmargin=max(14, rm))

    def scroll_by(self, units):
        self.txt.yview_scroll(units, "units")

    def show(self, markup):
        render_markup(self.txt, markup)

    def clear(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")


# ----------------------------------------------------------------------------
# Capsule button
# ----------------------------------------------------------------------------

class Button(tk.Canvas):
    """Capsule-shaped glass button. kind: primary | ghost | good | bad"""

    def __init__(self, master, th, text, command, kind="ghost", bg=None):
        self.th, self.kind, self.command = th, kind, command
        self.parent_bg = bg or th.GLASS
        self.font = tkfont.Font(family=th.ui_family, size=10)
        h = self.font.metrics("linespace") + 15
        w = self.font.measure(text) + 34
        super().__init__(master, width=w, height=h, bg=self.parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._bw, self._bh = w, h
        self._text = text
        self._render()
        for ev, fn in (("<Button-1>", self._click), ("<Enter>", self._hover),
                       ("<Leave>", self._unhover)):
            self.bind(ev, fn)

    def _colors(self, hover=False):
        th = self.th
        if self.kind == "primary":
            fill = "#6FE0F2" if hover else th.ACCENT
            return fill, "#08222A", fill
        if self.kind == "good":
            fill = "#69DDB0" if hover else th.GOOD
            return fill, "#062A1E", fill
        if self.kind == "bad":
            fill = "#FF9C88" if hover else th.BAD
            return fill, "#2E0F08", fill
        if self.kind == "flag":
            return th.FLAG_DIM, th.FLAG, th.FLAG
        return (th.GLASS_HI if hover else th.GLASS_LO), th.INK, th.EDGE

    def _capsule(self, x0, y0, x1, y1, color):
        r = (y1 - y0) / 2
        ids = [self.create_oval(x0, y0, x0 + 2 * r, y1, fill=color, outline=""),
               self.create_oval(x1 - 2 * r, y0, x1, y1, fill=color, outline=""),
               self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color,
                                     outline="")]
        return ids

    def _render(self, hover=False):
        self.delete("all")
        fill, fg, edge = self._colors(hover)
        self._capsule(0, 0, self._bw, self._bh, edge)          # 1px border
        self._capsule(1, 1, self._bw - 1, self._bh - 1, fill)
        self.create_text(self._bw / 2, self._bh / 2, text=self._text, fill=fg,
                         font=self.font)

    def _click(self, _=None):
        if self.command:
            self.command()

    def _hover(self, _=None):
        self._render(True)

    def _unhover(self, _=None):
        self._render(False)

    def set_text(self, t):
        self._text = t
        self._bw = self.font.measure(t) + 34
        self.configure(width=self._bw)
        self._render()

    def set_kind(self, kind):
        self.kind = kind
        self._bg = {"primary": self.th.ACCENT, "good": self.th.GOOD,
                    "bad": self.th.BAD}.get(kind, self.th.GLASS_LO)
        self._render()


def hairline(master, th, horizontal=True):
    if horizontal:
        return tk.Frame(master, bg=th.LINE, height=1)
    return tk.Frame(master, bg=th.LINE, width=1)


# ----------------------------------------------------------------------------
# Progress
# ----------------------------------------------------------------------------

def load_progress():
    """Returns (known, flagged)."""
    try:
        with open(PROGRESS_PATH) as f:
            d = json.load(f) or {}
        if not isinstance(d, dict):
            return set(), set()
        return set(d.get("known", [])), set(d.get("flagged", []))
    except Exception:
        return set(), set()


def save_progress(known, flagged):
    try:
        try:
            with open(PROGRESS_PATH) as f:
                d = json.load(f) or {}
        except Exception:
            d = {}
        if not isinstance(d, dict):
            d = {}
        d["known"] = sorted(known)
        d["flagged"] = sorted(flagged)
        with open(PROGRESS_PATH, "w") as f:
            json.dump(d, f, indent=1)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------------

class BrowseView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=app.th.GLASS)
        self.app, self.th = app, app.th
        th = self.th
        self.rows, self.current = {}, None

        side = tk.Frame(self, bg=th.GLASS, width=248)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        hairline(self, th, False).pack(side="left", fill="y")

        self.scroll = ScrollArea(side, th)
        self.scroll.pack(fill="both", expand=True, pady=(4, 4))
        self._build_list(self.scroll.inner)

        right = tk.Frame(self, bg=th.GLASS)
        right.pack(side="left", fill="both", expand=True)

        bar = tk.Frame(right, bg=th.GLASS, height=50)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.crumb = tk.Label(bar, text="", bg=th.GLASS, fg=th.MUTED,
                              font=th.eyebrow, anchor="w")
        self.crumb.pack(side="left", padx=(30, 0))
        self.mark_btn = Button(bar, th, "Mark as known", self._toggle_known)
        self.mark_btn.pack(side="right", padx=(0, 22))
        hairline(right, th).pack(fill="x")

        self.pane = ContentPane(right, th)
        self.pane.pack(fill="both", expand=True)
        if TOPICS:
            self.select(TOPICS[0]["id"])

    def _build_list(self, parent):
        th = self.th
        seen, groups = [], {}
        for t in TOPICS:
            if t["cat"] not in seen:
                seen.append(t["cat"])
                groups[t["cat"]] = []
            groups[t["cat"]].append(t)
        n = 0
        for cat in seen:
            tk.Label(parent, text=cat.upper(), bg=th.GLASS, fg=th.FAINT,
                     font=th.eyebrow, anchor="w").pack(
                fill="x", padx=(16, 10), pady=(16, 5))
            for t in groups[cat]:
                n += 1
                self._row(parent, t, n)

    def _row(self, parent, topic, n):
        th = self.th
        row = tk.Frame(parent, bg=th.GLASS, cursor="hand2")
        row.pack(fill="x", padx=(6, 4), pady=1)
        bar = tk.Frame(row, bg=th.GLASS, width=3)
        bar.pack(side="left", fill="y")
        num = tk.Label(row, text=f"{topic['n']:02d}", bg=th.GLASS, fg=th.FAINT,
                       font=th.mono_small, width=3, anchor="w")
        num.pack(side="left", padx=(8, 0))
        lbl = tk.Label(row, text=topic["title"], bg=th.GLASS, fg=th.INK,
                       font=th.small, anchor="w")
        lbl.pack(side="left", fill="x", expand=True, pady=5)
        dot = tk.Label(row, text="", bg=th.GLASS, fg=th.GOOD,
                       font=th.mono_small, width=2)
        dot.pack(side="right", padx=(0, 6))
        flg = tk.Label(row, text="", bg=th.GLASS, fg=th.FLAG,
                       font=th.mono_small, width=2)
        flg.pack(side="right")
        self.rows[topic["id"]] = (row, bar, num, lbl, dot, flg)
        for w in (row, num, lbl, dot, flg):
            w.bind("<Button-1>", lambda e, i=topic["id"]: self.select(i))
            w.bind("<Enter>", lambda e, i=topic["id"]: self._hover(i, True))
            w.bind("<Leave>", lambda e, i=topic["id"]: self._hover(i, False))

    def _hover(self, tid, on):
        if tid == self.current:
            return
        row, bar, num, lbl, dot, flg = self.rows[tid]
        bg = self.th.GLASS_HI if on else self.th.GLASS
        for w in (row, num, lbl, dot, flg):
            w.configure(bg=bg)
        bar.configure(bg=bg)

    def _paint(self):
        th = self.th
        ft = self.app.flagged_topics()
        for tid, (row, bar, num, lbl, dot, flg) in self.rows.items():
            act = tid == self.current
            bg = th.ACCENT_DIM if act else th.GLASS
            for w in (row, num, lbl, dot, flg):
                w.configure(bg=bg)
            bar.configure(bg=th.ACCENT if act else bg)
            lbl.configure(fg=th.ACCENT if act else th.INK,
                          font=th.body_bold if act else th.small)
            dot.configure(text="\u25cf" if tid in self.app.known else "")
            flg.configure(text="\u2691" if tid in ft else "")

    def select(self, tid, section=None):
        self.current = tid
        t = self.app.by_id[tid]
        self._paint()
        self.crumb.configure(
            text=f"{t['cat'].upper()}  \u2014  {t['title'].upper()}")
        self.pane.show("## " + t["q"] + "\n\n" + t["a"])
        self._sync()
        if section:
            self._scroll_to(section)
        self.app.set_status()

    def _scroll_to(self, heading):
        """Scroll the reading pane to a section heading and highlight it briefly."""
        txt = self.pane.txt
        idx = txt.search(heading, "1.0", stopindex="end")
        if not idx:
            return
        txt.see(idx)
        txt.update_idletasks()
        txt.yview_scroll(-2, "units")
        txt.tag_configure("jump", background=self.th.ACCENT_DIM)
        txt.tag_add("jump", idx, f"{idx} lineend")
        txt.after(2500, lambda: txt.tag_remove("jump", "1.0", "end"))

    def _sync(self):
        self.mark_btn.set_text(
            "Known \u2713" if self.current in self.app.known else "Mark as known")

    def _toggle_known(self):
        if self.current:
            self.app.toggle_known(self.current)
            self._sync()
            self._paint()


class CardsView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=app.th.GLASS)
        self.app, self.th = app, app.th
        th = self.th
        self.order = [t["id"] for t in TOPICS]
        self.idx, self.revealed, self.unknown_only = 0, False, False

        bar = tk.Frame(self, bg=th.GLASS, height=50)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.counter = tk.Label(bar, text="", bg=th.GLASS, fg=th.MUTED,
                                font=th.eyebrow, anchor="w")
        self.counter.pack(side="left", padx=(30, 0))
        self.filter_btn = Button(bar, th, "All topics", self._toggle_filter)
        self.filter_btn.pack(side="right", padx=(0, 22))
        Button(bar, th, "Shuffle", self._shuffle).pack(side="right", padx=(0, 8))
        hairline(self, th).pack(fill="x")

        qbox = tk.Frame(self, bg=th.GLASS)
        qbox.pack(fill="x", padx=32, pady=(22, 0))
        self.cat = tk.Label(qbox, text="", bg=th.GLASS, fg=th.ACCENT,
                            font=th.eyebrow, anchor="w")
        self.cat.pack(fill="x")
        self.q = tk.Label(qbox, text="", bg=th.GLASS, fg=th.INK,
                          font=th.question, anchor="w", justify="left",
                          wraplength=760)
        self.q.pack(fill="x", pady=(9, 0))
        qbox.bind("<Configure>",
                  lambda e: self.q.configure(wraplength=max(380, e.width - 8)))

        self.pane = ContentPane(self, th, pady=8)
        self.pane.pack(fill="both", expand=True, pady=(12, 0))

        hairline(self, th).pack(fill="x")
        foot = tk.Frame(self, bg=th.GLASS, height=62)
        foot.pack(fill="x")
        foot.pack_propagate(False)
        self.reveal_btn = Button(foot, th, "Reveal answer", self._reveal,
                                 kind="primary")
        self.reveal_btn.pack(side="left", padx=(30, 0), pady=13)
        Button(foot, th, "Next  \u2192", self._next).pack(
            side="right", padx=(0, 22), pady=13)
        Button(foot, th, "\u2190  Back", self._prev).pack(
            side="right", padx=(0, 8), pady=13)
        self.known_btn = Button(foot, th, "Mark as known", self._toggle_known)
        self.known_btn.pack(side="right", padx=(0, 8), pady=13)
        self._show()

    def _pool(self):
        if self.unknown_only:
            return [i for i in self.order if i not in self.app.known] or self.order
        return self.order

    def _show(self):
        pool = self._pool()
        self.idx %= max(len(pool), 1)
        self.cur = pool[self.idx]
        t = self.app.by_id[self.cur]
        self.revealed = False
        self.cat.configure(text=t["cat"].upper())
        self.q.configure(text=t["q"])
        self.pane.clear()
        self.reveal_btn.set_text("Reveal answer")
        self.counter.configure(text=f"CARD {self.idx + 1:02d} / {len(pool):02d}")
        self.known_btn.set_text(
            "Known \u2713" if self.cur in self.app.known else "Mark as known")

    def _reveal(self):
        if not self.revealed:
            self.revealed = True
            self.pane.show(self.app.by_id[self.cur]["a"])
            self.reveal_btn.set_text("Revealed")

    def _next(self):
        self.idx += 1
        self._show()

    def _prev(self):
        self.idx -= 1
        self._show()

    def _shuffle(self):
        random.shuffle(self.order)
        self.idx = 0
        self._show()

    def _toggle_filter(self):
        self.unknown_only = not self.unknown_only
        self.filter_btn.set_text(
            "Unrevised only" if self.unknown_only else "All topics")
        self.idx = 0
        self._show()

    def _toggle_known(self):
        self.app.toggle_known(self.cur)
        self.known_btn.set_text(
            "Known \u2713" if self.cur in self.app.known else "Mark as known")

    def on_key(self, e):
        if e.keysym == "space":
            self._next() if self.revealed else self._reveal()
        elif e.keysym == "Right":
            self._next()
        elif e.keysym == "Left":
            self._prev()


class QuizOption(tk.Frame):
    """One clickable answer row."""

    def __init__(self, master, th, key, on_click):
        super().__init__(master, bg=th.GLASS_LO, highlightthickness=1,
                         highlightbackground=th.LINE, highlightcolor=th.LINE,
                         cursor="hand2")
        self.th, self.on_click, self.index, self.locked = th, on_click, None, False
        self.k = tk.Label(self, text=key, bg=th.GLASS_LO, fg=th.FAINT,
                          font=th.mono_small, width=2)
        self.k.pack(side="left", padx=(14, 11), pady=11)
        self.txt = tk.Label(self, text="", bg=th.GLASS_LO, fg=th.INK, font=th.body,
                            anchor="w", justify="left", wraplength=620)
        self.txt.pack(side="left", fill="x", expand=True, padx=(0, 14), pady=11)
        for w in (self, self.k, self.txt):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._hover)
            w.bind("<Leave>", self._leave)
        self.bind("<Configure>",
                  lambda e: self.txt.configure(wraplength=max(220, e.width - 100)))

    def _paint(self, bg, border, fg, kfg):
        self.configure(bg=bg, highlightbackground=border, highlightcolor=border)
        self.k.configure(bg=bg, fg=kfg)
        self.txt.configure(bg=bg, fg=fg)

    def reset(self, text, index):
        self.index, self.locked = index, False
        self.txt.configure(text=text)
        self._paint(self.th.GLASS_LO, self.th.LINE, self.th.INK, self.th.FAINT)

    def mark(self, kind):
        th = self.th
        self.locked = True
        if kind == "correct":
            self._paint(th.GOOD_DIM, th.GOOD, th.INK, th.GOOD)
        elif kind == "wrong":
            self._paint(th.BAD_DIM, th.BAD, th.INK, th.BAD)
        else:
            self._paint(th.GLASS_LO, th.LINE, th.FAINT, th.FAINT)

    def _click(self, _=None):
        if not self.locked:
            self.on_click(self.index)

    def _hover(self, _=None):
        if not self.locked:
            self._paint(self.th.GLASS_HI, self.th.EDGE, self.th.INK, self.th.MUTED)

    def _leave(self, _=None):
        if not self.locked:
            self._paint(self.th.GLASS_LO, self.th.LINE, self.th.INK, self.th.FAINT)


class QuizView(tk.Frame):
    """Multiple choice quiz drawn from the authored question bank."""

    def __init__(self, master, app):
        super().__init__(master, bg=app.th.GLASS)
        self.app, self.th = app, app.th
        th = self.th
        self.order = list(range(len(QUIZ)))
        random.shuffle(self.order)
        self.i = self.right = self.asked = 0
        self.answered = False
        self.flagged_only = False
        self.correct = 0
        self.topic = None
        self.item = QUIZ[0]

        bar = tk.Frame(self, bg=th.GLASS, height=50)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.score = tk.Label(bar, text="", bg=th.GLASS, fg=th.MUTED,
                              font=th.eyebrow, anchor="w")
        self.score.pack(side="left", padx=(30, 0))
        Button(bar, th, "Reset session", self._reset).pack(side="right", padx=(0, 22))
        self.filter_btn = Button(bar, th, "All questions", self._toggle_filter)
        self.filter_btn.pack(side="right", padx=(0, 8))
        hairline(self, th).pack(fill="x")

        body = tk.Frame(self, bg=th.GLASS)
        body.pack(fill="both", expand=True, padx=30, pady=(22, 0))
        self.cat = tk.Label(body, text="", bg=th.GLASS, fg=th.ACCENT,
                            font=th.eyebrow, anchor="w")
        self.cat.pack(fill="x")
        self.q = tk.Label(body, text="", bg=th.GLASS, fg=th.INK, font=th.question,
                          anchor="w", justify="left", wraplength=740)
        self.q.pack(fill="x", pady=(9, 0))
        body.bind("<Configure>",
                  lambda e: self.q.configure(wraplength=max(380, e.width - 8)))

        self.options = []
        for n, key in enumerate("ABCD"):
            row = QuizOption(body, th, key, self._answer)
            row.pack(fill="x", pady=(10 if n == 0 else 7, 0))
            self.options.append(row)

        self.exp = tk.Frame(body, bg=th.GLASS_LO, highlightthickness=1,
                            highlightbackground=th.LINE)
        self.exp_lead = tk.Label(self.exp, text="", bg=th.GLASS_LO,
                                 font=th.eyebrow, anchor="w")
        self.exp_lead.pack(fill="x", padx=16, pady=(12, 4))
        self.exp_text = tk.Label(self.exp, text="", bg=th.GLASS_LO, fg=th.INK,
                                 font=th.small, anchor="w", justify="left",
                                 wraplength=700)
        self.exp_text.pack(fill="x", padx=16, pady=(0, 13))
        self.exp.bind("<Configure>",
                      lambda e: self.exp_text.configure(wraplength=max(240, e.width - 36)))

        self.locate = tk.Label(body, text="", bg=th.GLASS, fg=th.FAINT,
                               font=th.chrome, anchor="w", justify="left",
                               wraplength=740)
        body.bind("<Configure>", self._rewrap, add="+")

        hairline(self, th).pack(fill="x")
        foot = tk.Frame(self, bg=th.GLASS, height=62)
        foot.pack(fill="x")
        foot.pack_propagate(False)
        self.flag_btn = Button(foot, th, "\u2691  Mark for review", self._toggle_flag)
        self.flag_btn.pack(side="left", padx=(30, 0), pady=13)
        self.topic_btn = Button(foot, th, "Read full topic  \u2192", self._open_topic)
        Button(foot, th, "Next  \u2192", self._next).pack(side="right", padx=(0, 22),
                                                          pady=13)
        self._show()

    def _rewrap(self, e):
        self.locate.configure(wraplength=max(320, e.width - 8))

    def pool(self):
        if self.flagged_only:
            f = [i for i in self.order if QUIZ[i]["id"] in self.app.flagged]
            if f:
                return f
        return self.order

    def _toggle_filter(self):
        self.flagged_only = not self.flagged_only
        self.i = 0
        self._show()

    def _sync_filter(self):
        n = sum(1 for i in self.order if QUIZ[i]["id"] in self.app.flagged)
        self.filter_btn.set_text(
            "Flagged only (%d)" % n if self.flagged_only
            else ("All questions  \u00b7  %d flagged" % n if n else "All questions"))

    def _sync_flag(self):
        on = self.item["id"] in self.app.flagged
        self.flag_btn.set_text("\u2691  Marked \u2713" if on
                               else "\u2691  Mark for review")
        self.flag_btn.set_kind("flag" if on else "ghost")

    def _toggle_flag(self):
        qid = self.item["id"]
        self.app.flagged.discard(qid) if qid in self.app.flagged \
            else self.app.flagged.add(qid)
        self.app.persist()
        self.app.views["browse"]._paint()
        self._sync_flag()
        self._sync_filter()

    def _show(self):
        pool = self.pool()
        self.i %= len(pool)
        item = QUIZ[pool[self.i]]
        self.item = item
        self.answered = False
        self.topic = item["t"]
        t = self.app.by_id.get(item["t"])
        self.cat.configure(text=(t["cat"].upper() if t else ""))
        self.q.configure(text=item["q"])
        pairs = [(txt, idx == item["a"]) for idx, txt in enumerate(item["o"])]
        random.shuffle(pairs)
        self.correct = next(i for i, (_, ok) in enumerate(pairs) if ok)
        for i, row in enumerate(self.options):
            if i < len(pairs):
                row.reset(pairs[i][0], i)
                row.pack(fill="x", pady=(10 if i == 0 else 7, 0))
            else:
                row.pack_forget()
        self.exp.pack_forget()
        self.locate.pack_forget()
        self.topic_btn.pack_forget()
        self._sync_flag()
        self._sync_filter()
        self._score()

    def _score(self):
        pct = "%d%%" % round(100 * self.right / self.asked) if self.asked else "\u2014"
        self.score.configure(
            text="SESSION  %02d / %02d   \u00b7   %s" % (self.right, self.asked, pct))

    def _answer(self, pick):
        if self.answered:
            return
        self.answered = True
        ok = pick == self.correct
        self.asked += 1
        if ok:
            self.right += 1
            self.app.known.add(self.topic)
        else:
            self.app.known.discard(self.topic)
        self.app.persist()
        self.app.views["browse"]._paint()
        for i, row in enumerate(self.options):
            if row.index is None:
                continue
            row.mark("correct" if i == self.correct
                     else ("wrong" if i == pick else "dim"))
        self.exp_lead.configure(text="CORRECT" if ok else "NOT QUITE",
                                fg=self.th.GOOD if ok else self.th.BAD)
        why = re.sub(r"[`*]", "", self.item["why"])
        self.exp_text.configure(text=why)
        self.exp.pack(fill="x", pady=(18, 0))

        t = self.app.by_id.get(self.topic)
        if t:
            trail = "WHERE TO STUDY  \u00b7  #%02d  %s  \u2192  %s" % (
                t["n"], t["cat"].upper(), t["title"].upper())
            if self.item.get("sec"):
                trail += "  \u2192  " + self.item["sec"].upper()
            self.locate.configure(text=trail)
            self.locate.pack(fill="x", pady=(12, 0))

        self.topic_btn.set_text(
            ("Read that section  \u2192" if self.item.get("sec")
             else "Read full topic  \u2192"))
        self.topic_btn.pack(side="left", padx=(8, 0), pady=13)
        if not ok:
            self.app.flagged.add(self.item["id"])   # a miss is worth revisiting
            self.app.persist()
            self.app.views["browse"]._paint()
        self._sync_flag()
        self._sync_filter()
        self._score()

    def _open_topic(self):
        self.app.show("browse")
        self.app.views["browse"].select(self.topic, self.item.get("sec"))

    def _next(self):
        self.i += 1
        self._show()

    def _reset(self):
        self.right = self.asked = self.i = 0
        random.shuffle(self.order)
        self._show()

    def on_key(self, e):
        if e.keysym in ("f", "m"):
            self._toggle_flag()
        elif e.keysym in ("Return", "space"):
            self._next()
        else:
            k = "abcd".find(e.keysym.lower())
            if 0 <= k < 4 and not self.answered:
                self._answer(k)


class SearchView(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=app.th.GLASS)
        self.app, self.th = app, app.th
        th = self.th

        left = tk.Frame(self, bg=th.GLASS, width=300)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        hairline(self, th, False).pack(side="left", fill="y")

        box = tk.Frame(left, bg=th.EDGE)
        box.pack(fill="x", padx=14, pady=14)
        self.var = tk.StringVar()
        self.var.trace_add("write", lambda *a: self._run())
        self.entry = tk.Entry(box, textvariable=self.var, bd=0,
                              highlightthickness=0, bg=th.GLASS_LO, fg=th.INK,
                              font=th.body, insertbackground=th.ACCENT,
                              selectbackground=th.ACCENT_DIM)
        self.entry.pack(fill="x", padx=11, pady=9)

        self.count = tk.Label(left, text="TYPE TO SEARCH", bg=th.GLASS,
                              fg=th.FAINT, font=th.eyebrow, anchor="w")
        self.count.pack(fill="x", padx=16, pady=(0, 6))
        self.scroll = ScrollArea(left, th)
        self.scroll.pack(fill="both", expand=True, pady=(0, 8))

        right = tk.Frame(self, bg=th.GLASS)
        right.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(right, bg=th.GLASS, height=50)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.crumb = tk.Label(bar, text="", bg=th.GLASS, fg=th.MUTED,
                              font=th.eyebrow, anchor="w")
        self.crumb.pack(side="left", padx=(30, 0))
        hairline(right, th).pack(fill="x")
        self.pane = ContentPane(right, th)
        self.pane.pack(fill="both", expand=True)

    def focus_search(self):
        self.entry.focus_set()

    def _run(self):
        q = self.var.get().strip().lower()
        for w in self.scroll.inner.winfo_children():
            w.destroy()
        if len(q) < 2:
            self.count.configure(text="TYPE TO SEARCH")
            return
        hits = []
        for t in TOPICS:
            blob = (t["title"] + " " + t["q"] + " " + t["a"] + " " +
                    t["cat"]).lower()
            if q in blob:
                hits.append(((3 if q in t["title"].lower() else 0) +
                             (2 if q in t["q"].lower() else 0) +
                             blob.count(q), t))
        hits.sort(key=lambda x: -x[0])
        self.count.configure(
            text=f"{len(hits)} RESULT{'' if len(hits) == 1 else 'S'}")
        th = self.th
        for _, t in hits[:60]:
            row = tk.Frame(self.scroll.inner, bg=th.GLASS, cursor="hand2")
            row.pack(fill="x", padx=(6, 4), pady=1)
            b = tk.Frame(row, bg=th.GLASS, width=3)
            b.pack(side="left", fill="y")
            inner = tk.Frame(row, bg=th.GLASS)
            inner.pack(side="left", fill="x", expand=True, padx=(10, 8), pady=6)
            tl = tk.Label(inner, text=t["title"], bg=th.GLASS, fg=th.INK,
                          font=th.body_bold, anchor="w")
            tl.pack(fill="x")
            cl = tk.Label(inner, text=t["cat"], bg=th.GLASS, fg=th.FAINT,
                          font=th.mono_small, anchor="w")
            cl.pack(fill="x")
            grp = (row, inner, tl, cl)
            for w in grp:
                w.bind("<Button-1>", lambda e, x=t: self._open(x))
                w.bind("<Enter>", lambda e, g=grp, bb=b: self._hl(g, bb, True))
                w.bind("<Leave>", lambda e, g=grp, bb=b: self._hl(g, bb, False))

    def _hl(self, widgets, bar, on):
        bg = self.th.GLASS_HI if on else self.th.GLASS
        for w in widgets:
            w.configure(bg=bg)
        bar.configure(bg=self.th.ACCENT if on else bg)

    def _open(self, t):
        self.crumb.configure(
            text=f"{t['cat'].upper()}  \u2014  {t['title'].upper()}")
        self.pane.show("## " + t["q"] + "\n\n" + t["a"])


# ----------------------------------------------------------------------------
# App shell
# ----------------------------------------------------------------------------

class App(tk.Tk):
    MODES = [("browse", "Browse"), ("cards", "Cards"),
             ("quiz", "Quiz"), ("search", "Search")]

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1220x820")
        self.minsize(980, 660)
        self.th = Theme(self)
        th = self.th
        self.configure(bg="#%02x%02x%02x" % th.BASE_RGB)

        self.by_id = {t["id"]: t for t in TOPICS}
        self.q_by_id = {q["id"]: q for q in QUIZ}
        _known, _flagged = load_progress()
        self.known = {k for k in _known if k in self.by_id}
        self.flagged = {k for k in _flagged
                        if k in self.q_by_id
                        or (k.startswith("topic:") and k[6:] in self.by_id)}
        self.mode = None
        self._aurora = None
        self._aurora_size = (0, 0)
        self._resize_job = None

        self.cv = tk.Canvas(self, highlightthickness=0, bd=0,
                            bg="#%02x%02x%02x" % th.BASE_RGB)
        self.cv.pack(fill="both", expand=True)

        self.shell = tk.Frame(self.cv, bg=th.GLASS)

        # header
        head = tk.Frame(self.shell, bg=th.GLASS, height=52)
        head.pack(fill="x")
        head.pack_propagate(False)
        brand = tk.Frame(head, bg=th.GLASS)
        brand.pack(side="left")
        tk.Label(brand, text="FB", bg=th.ACCENT, fg="#07222A",
                 font=th.eyebrow, padx=7, pady=3).pack(side="left")
        tk.Label(brand, text="Study Guide", bg=th.GLASS, fg=th.INK,
                 font=th.title).pack(side="left", padx=(10, 0))
        self.tabs = {}
        nav = tk.Frame(head, bg=th.GLASS)
        nav.pack(side="right")
        for key, label in self.MODES:
            t = tk.Label(nav, text=label, bg=th.GLASS, fg=th.MUTED,
                         font=th.small, padx=13, pady=6, cursor="hand2")
            t.pack(side="left", padx=2)
            t.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.tabs[key] = t
        hairline(self.shell, th).pack(fill="x")

        self.body = tk.Frame(self.shell, bg=th.GLASS)
        self.body.pack(fill="both", expand=True)

        hairline(self.shell, th).pack(fill="x")
        foot = tk.Frame(self.shell, bg=th.GLASS, height=26)
        foot.pack(fill="x")
        foot.pack_propagate(False)
        self.status = tk.Label(foot, text="", bg=th.GLASS, fg=th.FAINT,
                               font=th.chrome, anchor="w")
        self.status.pack(side="left")
        tk.Label(foot, text="\u2190 \u2192  navigate     A\u2013D  answer     "
                            "F  flag     CTRL+F  search", bg=th.GLASS,
                 fg=th.FAINT, font=th.chrome).pack(side="right")

        self.views = {"browse": BrowseView(self.body, self),
                      "cards": CardsView(self.body, self),
                      "quiz": QuizView(self.body, self),
                      "search": SearchView(self.body, self)}
        self.show("browse")

        self.cv.bind("<Configure>", self._on_resize)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(seq, self._on_wheel)
        self.bind("<Control-f>", lambda e: self.show("search"))
        self.bind("<Command-f>", lambda e: self.show("search"))
        self.bind("<Key>", self._key)

    # -- backdrop -----------------------------------------------------------
    def _on_resize(self, e):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._place_shell(e.width, e.height)
        self._resize_job = self.after(140, lambda: self._paint(e.width, e.height))

    def _place_shell(self, w, h):
        m, i = self.th.MARGIN, self.th.INSET
        self.shell.place(x=m + i, y=m + i,
                         width=max(200, w - 2 * (m + i)),
                         height=max(200, h - 2 * (m + i)))

    def _paint(self, w, h):
        th = self.th
        self.cv.delete("bg")
        if (w, h) != self._aurora_size:
            self._aurora = make_aurora(w, h, th)
            self._aurora_size = (w, h)
        self.cv.create_image(0, 0, image=self._aurora, anchor="nw", tags="bg")
        m = th.MARGIN
        rounded_rect(self.cv, m + 2, m + 3, w - 2 * m, h - 2 * m, th.RADIUS,
                     fill="#050A12", outline="", tags="bg")        # soft shadow
        rounded_rect(self.cv, m, m, w - 2 * m, h - 2 * m, th.RADIUS,
                     fill=th.EDGE, outline="", tags="bg")          # specular edge
        rounded_rect(self.cv, m + 1, m + 1, w - 2 * m - 2, h - 2 * m - 2,
                     th.RADIUS - 1, fill=th.GLASS, outline="", tags="bg")
        self.cv.tag_lower("bg")

    # -- scrolling ----------------------------------------------------------
    def _on_wheel(self, e):
        units = wheel_units(e)
        if not units:
            return
        # Prefer the widget Tk delivered the event to. winfo_containing() is a
        # coordinate lookup and is unreliable on macOS for widgets embedded in
        # a canvas via create_window, which is how the scroll lists are built.
        w = getattr(e, "widget", None)
        if isinstance(w, str):
            try:
                w = self.nametowidget(w)
            except Exception:
                w = None
        if w is None:
            try:
                w = self.winfo_containing(e.x_root, e.y_root)
            except Exception:
                w = None
        while w is not None:
            if hasattr(w, "scroll_by"):
                w.scroll_by(units)
                return "break"
            w = getattr(w, "master", None)

    def _key(self, e):
        if self.mode == "cards" and e.keysym in ("space", "Left", "Right"):
            self.views["cards"].on_key(e)
        elif self.mode == "quiz" and e.keysym in (
                "a", "b", "c", "d", "f", "m", "Return", "space"):
            self.views["quiz"].on_key(e)

    # -- modes --------------------------------------------------------------
    def show(self, key):
        for v in self.views.values():
            v.pack_forget()
        self.views[key].pack(fill="both", expand=True)
        self.mode = key
        th = self.th
        for k, lbl in self.tabs.items():
            act = k == key
            lbl.configure(fg=th.ACCENT if act else th.MUTED,
                          bg=th.ACCENT_DIM if act else th.GLASS,
                          font=th.body_bold if act else th.small)
        if key == "search":
            self.after(60, self.views["search"].focus_search)
        self.set_status()

    def toggle_known(self, tid):
        self.known.discard(tid) if tid in self.known else self.known.add(tid)
        self.persist()

    def persist(self):
        save_progress(self.known, self.flagged)
        self.set_status()

    def flagged_topics(self):
        out = set()
        for k in self.flagged:
            if k.startswith("topic:"):
                out.add(k[6:])
            elif k in self.q_by_id:
                out.add(self.q_by_id[k]["t"])
        return out

    def set_status(self):
        total, n = len(TOPICS), len(self.known)
        pct = round(100 * n / total) if total else 0
        blocks = round(pct / 5)
        meter = "\u2588" * blocks + "\u2591" * (20 - blocks)
        fl = f"  \u00b7  {len(self.flagged)} FLAGGED" if self.flagged else ""
        self.status.configure(
            text=f"{meter}  {n:02d}/{total} KNOWN  \u00b7  {pct}%{fl}  "
                 f"\u00b7  {(self.mode or '').upper()}")

# ----------------------------------------------------------------------------
# Web UI — real backdrop-filter glass, served locally
# ----------------------------------------------------------------------------

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FB Study Guide</title>
<style>
:root{
  --blur: 34px;
  --tint: 0.07;
  --radius: 26px;
  --base: #070E18;
  --b1:#164A63; --b2:#2E1C55; --b3:#0C5058; --b4:#18306A;
  --ink:#EAF2F7;
  --muted:#9DB1C1;
  --faint:#6E8496;
  --line: rgba(255,255,255,.09);
  --edge: rgba(255,255,255,.16);
  --accent:#5AD2E6;
  --accent-dim: rgba(90,210,230,.14);
  --good:#4ED8A4;
  --bad:#FF9077;
  --flag:#FFC86B;
  --code-bg: rgba(0,0,0,.30);
  --code-fg:#A9DCEC;
  --ui: ui-sans-serif, -apple-system, "SF Pro Text", "Inter", "Segoe UI", system-ui, sans-serif;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
}
*{box-sizing:border-box}
/* The hidden attribute must win over author display rules such as .opts{display:flex};
   without !important the UA rule loses the cascade and hidden elements stay visible. */
[hidden]{display:none !important}
html,body{height:100%}
body{
  margin:0; font-family:var(--ui); color:var(--ink);
  background:var(--base); overflow:hidden;
  -webkit-font-smoothing:antialiased;
}
/* ---- backdrop ---------------------------------------------------------- */
#bg{position:fixed; inset:0; z-index:0; overflow:hidden; background:var(--base);
    background-size:cover; background-position:center;}
.blob{position:absolute; width:62vmax; height:62vmax; border-radius:50%;
      filter:blur(90px); opacity:.72; will-change:transform;}
.b1{background:var(--b1); left:-14%;  top:-18%;  animation:d1 52s ease-in-out infinite alternate;}
.b2{background:var(--b2); right:-16%; top:-10%;  animation:d2 64s ease-in-out infinite alternate;}
.b3{background:var(--b3); right:-10%; bottom:-22%;animation:d3 58s ease-in-out infinite alternate;}
.b4{background:var(--b4); left:-8%;   bottom:-20%;animation:d4 70s ease-in-out infinite alternate;}
@keyframes d1{to{transform:translate3d(7vw,5vh,0) scale(1.10)}}
@keyframes d2{to{transform:translate3d(-6vw,7vh,0) scale(1.06)}}
@keyframes d3{to{transform:translate3d(-8vw,-5vh,0) scale(1.12)}}
@keyframes d4{to{transform:translate3d(6vw,-6vh,0) scale(1.05)}}
body.wallpaper .blob{display:none}
body.wallpaper #bg::after{content:""; position:absolute; inset:0;
  background:linear-gradient(180deg, rgba(0,0,0,.34), rgba(0,0,0,.52));}

/* ---- glass surface ----------------------------------------------------- */
#app{
  position:relative; z-index:1; height:100vh; padding:18px;
  display:flex; flex-direction:column;
}
.surface{
  flex:1; min-height:0; display:flex; flex-direction:column;
  border-radius:var(--radius);
  background:rgba(255,255,255,var(--tint));
  backdrop-filter:blur(var(--blur)) saturate(150%);
  -webkit-backdrop-filter:blur(var(--blur)) saturate(150%);
  border:1px solid var(--edge);
  box-shadow:0 24px 70px rgba(0,0,0,.48), inset 0 1px 0 rgba(255,255,255,.14);
  overflow:hidden; position:relative;
}
.surface::before{
  content:""; position:absolute; inset:0 0 auto 0; height:44%; pointer-events:none;
  background:linear-gradient(180deg, rgba(255,255,255,.07), transparent);
}
/* ---- header ------------------------------------------------------------ */
header{display:flex; align-items:center; gap:16px; padding:0 20px; height:56px;
       border-bottom:1px solid var(--line); flex:0 0 auto; position:relative;}
.brand{display:flex; align-items:center; gap:10px; font-weight:650; font-size:15px;}
.badge{font-family:var(--mono); font-size:10px; font-weight:700; letter-spacing:.06em;
       background:var(--accent); color:#06222B; padding:3px 7px; border-radius:6px;}
nav{margin-left:auto; display:flex; gap:4px}
nav button{
  font:inherit; font-size:13px; color:var(--muted); background:transparent;
  border:0; padding:7px 14px; border-radius:999px; cursor:pointer;
  transition:background .16s ease, color .16s ease;
}
nav button:hover{background:rgba(255,255,255,.07); color:var(--ink)}
nav button[aria-current="true"]{background:var(--accent-dim); color:var(--accent); font-weight:600}
.icon-btn{
  font:inherit; font-size:15px; line-height:1; color:var(--muted); background:transparent;
  border:1px solid var(--line); width:32px; height:32px; border-radius:999px;
  cursor:pointer; display:grid; place-items:center; transition:.16s ease;
}
.icon-btn:hover{color:var(--ink); border-color:var(--edge); background:rgba(255,255,255,.07)}

/* ---- body -------------------------------------------------------------- */
.viewwrap{flex:1; min-height:0; display:flex; flex-direction:column}
.view{flex:1; min-height:0; display:none; flex-direction:column; animation:fade .22s ease}
.view.on{display:flex}
@keyframes fade{from{opacity:0; transform:translateY(4px)} to{opacity:1; transform:none}}
.split{flex:1; min-height:0; display:flex}
.sidebar{width:264px; flex:0 0 auto; overflow-y:auto; padding:8px 4px 16px 6px;
         border-right:1px solid var(--line)}
.pane{flex:1; min-width:0; display:flex; flex-direction:column}
.panebar{height:50px; flex:0 0 auto; display:flex; align-items:center; gap:12px;
         padding:0 20px 0 26px; border-bottom:1px solid var(--line)}
.crumb{font-family:var(--mono); font-size:10px; letter-spacing:.10em; color:var(--muted);
       text-transform:uppercase; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.scroller{flex:1; min-height:0; overflow-y:auto; padding:22px 26px 40px}
.reading{max-width:78ch}

/* ---- sidebar items ----------------------------------------------------- */
.cat{font-family:var(--mono); font-size:9.5px; font-weight:700; letter-spacing:.14em;
     color:var(--faint); text-transform:uppercase; padding:18px 12px 6px 14px}
.item{display:flex; align-items:center; gap:9px; width:100%; text-align:left;
      font:inherit; font-size:13px; color:var(--ink); background:transparent; border:0;
      padding:7px 10px 7px 8px; border-radius:10px; cursor:pointer;
      border-left:3px solid transparent; transition:background .15s ease;}
.item:hover{background:rgba(255,255,255,.06)}
.item[aria-current="true"]{background:var(--accent-dim); border-left-color:var(--accent);
      color:var(--accent); font-weight:600}
.item .n{font-family:var(--mono); font-size:10px; color:var(--faint); min-width:18px}
.item .t{flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.item .dot{width:6px; height:6px; border-radius:50%; background:var(--good); opacity:0}
.item.known .dot{opacity:1}

/* ---- buttons ----------------------------------------------------------- */
.btn{
  font:inherit; font-size:12.5px; color:var(--ink); background:rgba(255,255,255,.06);
  border:1px solid var(--line); padding:8px 16px; border-radius:999px; cursor:pointer;
  transition:.16s ease; white-space:nowrap;
}
.btn:hover{background:rgba(255,255,255,.12); border-color:var(--edge)}
.btn.primary{background:var(--accent); color:#06222B; border-color:transparent; font-weight:600}
.btn.primary:hover{background:#77E2F3}
.btn.good{background:var(--good); color:#052A1E; border-color:transparent; font-weight:600}
.btn.bad{background:var(--bad); color:#2E0D05; border-color:transparent; font-weight:600}
.btn:disabled{opacity:.5; cursor:default}
.spacer{margin-left:auto}
:focus-visible{outline:2px solid var(--accent); outline-offset:2px}

/* ---- prose ------------------------------------------------------------- */
.prose{font-size:14.5px; line-height:1.62; color:var(--ink)}
.prose h3{font-size:14.5px; font-weight:650; margin:26px 0 8px; letter-spacing:.005em}
.prose h3:first-child{margin-top:0}
.prose .q{font-size:19px; font-weight:600; line-height:1.35; margin:0 0 18px}
.prose p{margin:0 0 12px}
.prose ul{margin:0 0 12px; padding-left:20px}
.prose li{margin:0 0 5px}
.prose strong{font-weight:650; color:#fff}
.prose em{font-style:italic; color:#F2F8FC}
.prose code{font-family:var(--mono); font-size:.86em; background:var(--code-bg);
            color:var(--code-fg); padding:1.5px 5px; border-radius:5px}
.prose pre{font-family:var(--mono); font-size:12px; line-height:1.62; background:var(--code-bg);
  border:1px solid var(--line); border-radius:12px; padding:13px 15px; overflow-x:auto;
  margin:0 0 14px; color:var(--code-fg)}
.prose pre code{background:none; padding:0; font-size:inherit; color:inherit}

/* ---- cards / quiz ------------------------------------------------------ */
.eyebrow{font-family:var(--mono); font-size:10px; font-weight:700; letter-spacing:.14em;
         color:var(--accent); text-transform:uppercase; margin-bottom:10px}
.qhead{padding:24px 26px 0}
.qtext{font-size:20px; font-weight:600; line-height:1.35; max-width:70ch}
.foot{height:62px; flex:0 0 auto; display:flex; align-items:center; gap:8px;
      padding:0 20px 0 26px; border-top:1px solid var(--line)}
textarea{
  width:100%; font:inherit; font-size:14px; line-height:1.55; color:var(--ink);
  background:rgba(0,0,0,.24); border:1px solid var(--line); border-radius:12px;
  padding:12px 14px; resize:none; min-height:112px; transition:.16s ease;
}
textarea:focus{outline:none; border-color:var(--accent); background:rgba(0,0,0,.32)}
textarea:disabled{opacity:.75; min-height:70px}
.hint{font-size:12px; color:var(--faint); margin-top:8px}

/* ---- multiple choice --------------------------------------------------- */
.opts{display:flex; flex-direction:column; gap:9px; margin-top:20px; max-width:72ch}
.opt{display:flex; gap:12px; align-items:flex-start; width:100%; text-align:left;
  font:inherit; font-size:14px; line-height:1.5; color:var(--ink);
  background:rgba(255,255,255,.045); border:1px solid var(--line);
  border-radius:14px; padding:12px 16px; cursor:pointer; transition:.16s ease}
.opt:hover:not(:disabled){background:rgba(255,255,255,.11); border-color:var(--edge)}
.opt:disabled{cursor:default}
.opt .k{font-family:var(--mono); font-size:10.5px; color:var(--faint); flex:0 0 auto;
  border:1px solid var(--line); border-radius:6px; padding:2px 7px; margin-top:1px}
.opt.correct{background:rgba(78,216,164,.15); border-color:var(--good)}
.opt.correct .k{color:var(--good); border-color:var(--good)}
.opt.wrong{background:rgba(255,144,119,.13); border-color:var(--bad)}
.opt.wrong .k{color:var(--bad); border-color:var(--bad)}
.opt.dim{opacity:.45}
.explain{margin:22px 0 8px; padding:15px 18px; border-radius:14px; max-width:72ch;
  background:rgba(0,0,0,.22); border:1px solid var(--line); font-size:13.5px; line-height:1.6}
.explain .lead{font-family:var(--mono); font-size:9.5px; letter-spacing:.14em;
  text-transform:uppercase; font-weight:700; margin-bottom:7px}
.explain.ok .lead{color:var(--good)}
.explain.no .lead{color:var(--bad)}
.qwrap{padding:0 26px}

/* ---- flagging + location hints ----------------------------------------- */
.qrow{display:flex; align-items:flex-start; gap:14px; max-width:78ch}
.flag{font:inherit; font-size:15px; line-height:1; color:var(--faint); flex:0 0 auto;
  background:transparent; border:1px solid var(--line); width:34px; height:34px;
  border-radius:999px; cursor:pointer; display:grid; place-items:center;
  transition:.16s ease; margin-top:3px}
.flag:hover{color:var(--ink); border-color:var(--edge); background:rgba(255,255,255,.08)}
.flag.on{color:var(--flag); border-color:var(--flag); background:rgba(255,200,107,.15)}
.locate{margin-top:15px; max-width:72ch; font-family:var(--mono); font-size:10px;
  letter-spacing:.09em; text-transform:uppercase; color:var(--faint); line-height:1.8}
.locate b{color:var(--muted); font-weight:600}
.locate .arw{color:var(--accent); opacity:.8}
.item .fl{color:var(--flag); font-size:10px; opacity:0; flex:0 0 auto}
.item.flagged .fl{opacity:1}
@keyframes pulse{0%{background:var(--accent-dim)} 100%{background:transparent}}
.prose h3.jump{animation:pulse 2.4s ease-out; border-radius:7px;
  padding:3px 7px; margin-left:-7px}

/* ---- search ------------------------------------------------------------ */
.searchbox{padding:14px 12px 8px}
.searchbox input{
  width:100%; font:inherit; font-size:14px; color:var(--ink);
  background:rgba(0,0,0,.24); border:1px solid var(--line); border-radius:12px;
  padding:10px 14px; transition:.16s ease;
}
.searchbox input:focus{outline:none; border-color:var(--accent); background:rgba(0,0,0,.32)}
.rescount{font-family:var(--mono); font-size:9.5px; letter-spacing:.14em; color:var(--faint);
          text-transform:uppercase; padding:6px 14px 8px}
.hit{display:block; width:100%; text-align:left; font:inherit; background:transparent;
     border:0; border-left:3px solid transparent; padding:8px 12px; border-radius:10px;
     cursor:pointer; transition:background .15s ease}
.hit:hover{background:rgba(255,255,255,.06); border-left-color:var(--accent)}
.hit .ht{font-size:13.5px; font-weight:600; color:var(--ink)}
.hit .hc{font-family:var(--mono); font-size:10px; color:var(--faint); margin-top:2px}
mark{background:var(--accent-dim); color:var(--accent); border-radius:3px; padding:0 2px}

/* ---- status ------------------------------------------------------------ */
.status{height:28px; flex:0 0 auto; display:flex; align-items:center; gap:16px;
        padding:0 22px; border-top:1px solid var(--line);
        font-family:var(--mono); font-size:10px; letter-spacing:.08em; color:var(--faint)}
.meter{letter-spacing:-.5px; color:var(--accent); opacity:.75}
.keys{margin-left:auto; display:flex; gap:14px}

/* ---- settings ---------------------------------------------------------- */
.sheet{
  position:absolute; top:0; right:0; bottom:0; width:320px; z-index:5;
  background:rgba(255,255,255,calc(var(--tint) + .05));
  backdrop-filter:blur(46px) saturate(160%);
  -webkit-backdrop-filter:blur(46px) saturate(160%);
  border-left:1px solid var(--edge); padding:20px 22px; overflow-y:auto;
  transform:translateX(100%); transition:transform .28s cubic-bezier(.4,0,.2,1);
  box-shadow:-20px 0 60px rgba(0,0,0,.4);
}
.sheet.on{transform:none}
.sheet h4{font-family:var(--mono); font-size:9.5px; letter-spacing:.14em; font-weight:700;
          text-transform:uppercase; color:var(--faint); margin:22px 0 10px}
.sheet h4:first-of-type{margin-top:14px}
.sheettop{display:flex; align-items:center; justify-content:space-between}
.sheettop strong{font-size:14px}
.swatches{display:grid; grid-template-columns:repeat(3,1fr); gap:9px}
.sw{height:52px; border-radius:12px; border:1px solid var(--line); cursor:pointer;
    position:relative; overflow:hidden; transition:.16s ease}
.sw:hover{border-color:var(--edge); transform:translateY(-1px)}
.sw[aria-pressed="true"]{border-color:var(--accent); box-shadow:0 0 0 2px var(--accent-dim)}
.sw span{position:absolute; left:0; right:0; bottom:0; font-family:var(--mono); font-size:8.5px;
  letter-spacing:.1em; text-transform:uppercase; text-align:center; padding:3px 0;
  background:rgba(0,0,0,.45); color:#fff}
.row{display:flex; align-items:center; gap:10px; margin-bottom:12px}
.row label{font-size:12px; color:var(--muted); min-width:52px}
input[type=range]{flex:1; accent-color:var(--accent); background:transparent}
.filelab{display:block; text-align:center; font-size:12.5px; padding:10px;
  border:1px dashed var(--line); border-radius:12px; cursor:pointer; color:var(--muted);
  transition:.16s ease}
.filelab:hover{border-color:var(--accent); color:var(--ink)}
input[type=file]{display:none}
.note{font-size:11.5px; color:var(--faint); line-height:1.5; margin-top:10px}

/* ---- scrollbars -------------------------------------------------------- */
*::-webkit-scrollbar{width:9px; height:9px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:rgba(255,255,255,.16); border-radius:999px;
  border:2px solid transparent; background-clip:content-box}
*::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.30); background-clip:content-box}

@media (max-width:860px){
  .sidebar{width:210px}
  #app{padding:10px}
  .keys{display:none}
}
@media (prefers-reduced-motion: reduce){
  .blob{animation:none}
  *{transition-duration:.01ms !important}
  .view{animation:none}
}
</style>
</head>
<body>
<div id="bg">
  <div class="blob b1"></div><div class="blob b2"></div>
  <div class="blob b3"></div><div class="blob b4"></div>
</div>

<div id="app">
 <div class="surface">
  <header>
    <div class="brand"><span class="badge">FB</span> Study Guide</div>
    <nav id="nav">
      <button data-mode="browse" aria-current="true">Browse</button>
      <button data-mode="cards">Cards</button>
      <button data-mode="quiz">Quiz</button>
      <button data-mode="search">Search</button>
    </nav>
    <button class="icon-btn" id="gear" title="Appearance" aria-label="Appearance">&#9881;</button>
  </header>

  <div class="viewwrap">
    <!-- BROWSE -->
    <section class="view on" id="v-browse">
      <div class="split">
        <aside class="sidebar" id="tree"></aside>
        <div class="pane">
          <div class="panebar">
            <div class="crumb" id="b-crumb"></div>
            <button class="btn spacer" id="b-known">Mark as known</button>
          </div>
          <div class="scroller"><div class="prose reading" id="b-body"></div></div>
        </div>
      </div>
    </section>

    <!-- CARDS -->
    <section class="view" id="v-cards">
      <div class="panebar">
        <div class="crumb" id="c-count"></div>
        <button class="btn spacer" id="c-shuffle">Shuffle</button>
        <button class="btn" id="c-filter">All topics</button>
      </div>
      <div class="qhead">
        <div class="eyebrow" id="c-cat"></div>
        <div class="qtext" id="c-q"></div>
      </div>
      <div class="scroller"><div class="prose reading" id="c-a"></div></div>
      <div class="foot">
        <button class="btn primary" id="c-reveal">Reveal answer</button>
        <button class="btn spacer" id="c-known">Mark as known</button>
        <button class="btn" id="c-prev">&#8592;&nbsp; Back</button>
        <button class="btn" id="c-next">Next &nbsp;&#8594;</button>
      </div>
    </section>

    <!-- QUIZ -->
    <section class="view" id="v-quiz">
      <div class="panebar">
        <div class="crumb" id="q-score"></div>
        <button class="btn spacer" id="q-filter">All questions</button>
        <button class="btn" id="q-mode">Switch to recall</button>
        <button class="btn" id="q-reset">Reset session</button>
      </div>
      <div class="scroller" style="padding-top:24px">
        <div class="qwrap">
          <div class="eyebrow" id="q-cat"></div>
          <div class="qrow">
            <div class="qtext" id="q-q"></div>
            <button class="flag" id="q-flag" aria-pressed="false"
                    title="Mark for review">&#9873;</button>
          </div>
          <div class="opts" id="q-opts"></div>
          <div id="q-recall" hidden style="margin-top:18px; max-width:72ch">
            <textarea id="q-input" placeholder="Answer from memory&hellip;"></textarea>
            <div class="hint" id="q-hint">Answer from memory, then check yourself.</div>
          </div>
          <div id="q-explain"></div>
          <div id="q-locate"></div>
          <div class="prose reading" id="q-a" style="margin-top:18px"></div>
        </div>
      </div>
      <div class="foot">
        <button class="btn primary" id="q-check" hidden>Check answer</button>
        <button class="btn good" id="q-got" hidden>Got it</button>
        <button class="btn bad" id="q-miss" hidden>Needs review</button>
        <button class="btn" id="q-topic" hidden>Read full topic &nbsp;&#8594;</button>
        <button class="btn spacer" id="q-next">Next &nbsp;&#8594;</button>
      </div>
    </section>

    <!-- SEARCH -->
    <section class="view" id="v-search">
      <div class="split">
        <aside class="sidebar" style="width:300px">
          <div class="searchbox"><input id="s-input" placeholder="Search all topics"
            autocomplete="off" spellcheck="false"></div>
          <div class="rescount" id="s-count">Type to search</div>
          <div id="s-hits"></div>
        </aside>
        <div class="pane">
          <div class="panebar"><div class="crumb" id="s-crumb"></div></div>
          <div class="scroller"><div class="prose reading" id="s-body"></div></div>
        </div>
      </div>
    </section>
  </div>

  <div class="status">
    <span class="meter" id="st-meter"></span>
    <span id="st-text"></span>
    <span class="keys">
      <span>&#8592; &#8594; navigate</span><span>SPACE reveal</span><span>A&ndash;D answer</span><span>F flag</span><span>/ search</span>
    </span>
  </div>

  <!-- SETTINGS -->
  <aside class="sheet" id="sheet">
    <div class="sheettop"><strong>Appearance</strong>
      <button class="icon-btn" id="sheet-close" aria-label="Close">&times;</button></div>

    <h4>Backdrop</h4>
    <div class="swatches" id="swatches"></div>

    <h4>Wallpaper</h4>
    <label class="filelab" for="wp">Choose an image&hellip;</label>
    <input type="file" id="wp" accept="image/*">
    <button class="btn" id="wp-clear" style="width:100%; margin-top:8px">Remove wallpaper</button>

    <h4>Glass</h4>
    <div class="row"><label for="r-blur">Blur</label>
      <input type="range" id="r-blur" min="0" max="80" step="1"></div>
    <div class="row"><label for="r-tint">Tint</label>
      <input type="range" id="r-tint" min="0" max="24" step="1"></div>

    <h4>Progress</h4>
    <button class="btn" id="reset-prog" style="width:100%">Clear all "known" marks</button>
    <button class="btn" id="reset-flags" style="width:100%; margin-top:8px">Clear all review flags</button>
    <div class="note">Settings and progress are stored locally in your home folder.
      Nothing leaves this machine.</div>
  </aside>
 </div>
</div>
<script>
const TOKEN = "__TOKEN__";
</script>
"""


HTML_PAGE += r"""
<script>
/* ---------- markup renderer (mirrors the Python one) ---------- */
function esc(s){return s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function inline(s){
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*([^*<>]+)\*/g, '<em>$1</em>');
}
function renderMarkup(text){
  const out = []; let inCode = false, code = [], list = [], para = [];
  const flushPara = () => { if (para.length){ out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; } };
  const flushList = () => { if (list.length){ out.push('<ul>' + list.map(x => '<li>' + inline(x) + '</li>').join('') + '</ul>'); list = []; } };
  const flushAll  = () => { flushPara(); flushList(); };
  const flushCode = () => {
    while (code.length && !code[0].trim()) code.shift();
    while (code.length && !code[code.length-1].trim()) code.pop();
    if (code.length) out.push('<pre><code>' + esc(code.join('\n')) + '</code></pre>');
    code = [];
  };
  for (const line of text.split('\n')){
    if (line.trim().startsWith('```')){
      if (inCode) flushCode(); else flushAll();
      inCode = !inCode; continue;
    }
    if (inCode){ code.push(line); continue; }
    if (line.startsWith('## ')){ flushAll(); out.push('<h3>' + inline(line.slice(3)) + '</h3>'); }
    else if (line.startsWith('- ')){ flushPara(); list.push(line.slice(2)); }
    else if (line.startsWith('  ') && line.trim() && list.length){
      list[list.length-1] += ' ' + line.trim();
    }
    else if (!line.trim()){ flushAll(); }
    else { flushList(); para.push(line); }
  }
  if (inCode) flushCode();
  flushAll();
  return out.join('');
}
const answerHTML = t => '<div class="q">' + esc(t.q) + '</div>' + renderMarkup(t.a);

/* ---------- state ---------- */
const $ = s => document.querySelector(s);
const PRESETS = {
  abyss:  {label:'Abyss',  base:'#070E18', b:['#164A63','#2E1C55','#0C5058','#18306A']},
  nebula: {label:'Nebula', base:'#0B0715', b:['#4A1D6B','#8B2A6B','#2A1B6B','#5C1F4A']},
  aurora: {label:'Aurora', base:'#04120F', b:['#0F5C4A','#1A6B5C','#164A63','#33632A']},
  ember:  {label:'Ember',  base:'#150A08', b:['#5C2A1A','#7A3A1F','#3A1A2A','#6B4A1A']},
  slate:  {label:'Slate',  base:'#0C1116', b:['#243447','#2E3D4F','#1C2A38','#33465C']},
  ink:    {label:'Ink',    base:'#08080B', b:['#1C1C24','#26262F','#141419','#2E2E38']},
};
let TOPICS = [], QUIZ = [], byId = {}, qById = {}, mode = 'browse';
let known = new Set(), flagged = new Set();
let settings = {preset:'abyss', blur:34, tint:7, wallpaper:false};

const api = (p, o={}) => fetch(p + (p.includes('?')?'&':'?') + 't=' + TOKEN, o);
let saveTimer = null;
function save(){
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    api('/api/state', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({known:[...known], flagged:[...flagged], settings})}).catch(()=>{});
  }, 250);
}

/* ---------- appearance ---------- */
function applySettings(){
  const r = document.documentElement.style;
  const p = PRESETS[settings.preset] || PRESETS.abyss;
  r.setProperty('--base', p.base);
  p.b.forEach((c,i) => r.setProperty('--b'+(i+1), c));
  r.setProperty('--blur', settings.blur + 'px');
  r.setProperty('--tint', (settings.tint/100).toFixed(3));
  document.body.classList.toggle('wallpaper', !!settings.wallpaper);
  $('#bg').style.backgroundImage = settings.wallpaper
    ? 'url(/wallpaper?t=' + TOKEN + '&v=' + (settings.wpv||0) + ')' : '';
  $('#r-blur').value = settings.blur;
  $('#r-tint').value = settings.tint;
  document.querySelectorAll('.sw').forEach(el =>
    el.setAttribute('aria-pressed', String(!settings.wallpaper && el.dataset.k === settings.preset)));
}
function buildSwatches(){
  $('#swatches').innerHTML = Object.entries(PRESETS).map(([k,p]) =>
    `<button class="sw" data-k="${k}" style="background:
       radial-gradient(circle at 22% 22%, ${p.b[0]}, transparent 62%),
       radial-gradient(circle at 78% 28%, ${p.b[1]}, transparent 62%),
       radial-gradient(circle at 70% 82%, ${p.b[2]}, transparent 62%),
       ${p.base}"><span>${p.label}</span></button>`).join('');
  document.querySelectorAll('.sw').forEach(el => el.onclick = () => {
    settings.preset = el.dataset.k; settings.wallpaper = false;
    applySettings(); save();
  });
}

/* ---------- status ---------- */
function status(){
  const n = known.size, total = TOPICS.length;
  const pct = total ? Math.round(100*n/total) : 0;
  const blocks = Math.round(pct/5);
  $('#st-meter').textContent = '\u2588'.repeat(blocks) + '\u2591'.repeat(20-blocks);
  const fl = flagged.size ? ` \u00b7 ${flagged.size} FLAGGED` : '';
  $('#st-text').textContent = `${String(n).padStart(2,'0')}/${total} KNOWN \u00b7 ${pct}%${fl} \u00b7 ${mode.toUpperCase()}`;
}
function toggleKnown(id){
  known.has(id) ? known.delete(id) : known.add(id);
  save(); status(); paintTree(); syncKnownButtons();
}
function syncKnownButtons(){
  $('#b-known').textContent = known.has(B.cur) ? 'Known \u2713' : 'Mark as known';
  $('#c-known').textContent = known.has(C.cur) ? 'Known \u2713' : 'Mark as known';
}

/* ---------- browse ---------- */
const B = {cur:null};
function buildTree(){
  const seen = [], groups = {};
  TOPICS.forEach(t => { if(!groups[t.cat]){groups[t.cat]=[]; seen.push(t.cat);} groups[t.cat].push(t); });
  let html = '';
  for (const cat of seen){
    html += `<div class="cat">${esc(cat)}</div>`;
    for (const t of groups[cat]){
      html += `<button class="item" data-id="${t.id}"><span class="n">${String(t.n).padStart(2,'0')}</span>
        <span class="t">${esc(t.title)}</span><span class="fl">&#9873;</span><span class="dot"></span></button>`;
    }
  }
  $('#tree').innerHTML = html;
  document.querySelectorAll('#tree .item').forEach(el =>
    el.onclick = () => selectTopic(el.dataset.id));
}
function flaggedTopics(){
  const out = new Set();
  for (const key of flagged){
    if (key.startsWith('topic:')) out.add(key.slice(6));
    else if (qById[key]) out.add(qById[key].t);
  }
  return out;
}
function paintTree(){
  const ft = flaggedTopics();
  document.querySelectorAll('#tree .item').forEach(el => {
    el.setAttribute('aria-current', String(el.dataset.id === B.cur));
    el.classList.toggle('known', known.has(el.dataset.id));
    el.classList.toggle('flagged', ft.has(el.dataset.id));
  });
}
function selectTopic(id, section){
  B.cur = id; const t = byId[id];
  $('#b-crumb').textContent = t.cat + '  \u2014  ' + t.title;
  $('#b-body').innerHTML = answerHTML(t);
  $('#v-browse .scroller').scrollTop = 0;
  paintTree(); syncKnownButtons();
  if (section){
    const h = [...$('#b-body').querySelectorAll('h3')]
      .find(x => x.textContent.trim() === section);
    if (h){
      h.classList.add('jump');
      if (h.scrollIntoView){
        requestAnimationFrame(() => h.scrollIntoView({block:'center', behavior:'smooth'}));
      }
      setTimeout(() => h.classList.remove('jump'), 2500);
    }
  }
}

/* ---------- cards ---------- */
const C = {order:[], i:0, revealed:false, unknownOnly:false, cur:null};
const cardPool = () => C.unknownOnly
  ? (C.order.filter(id => !known.has(id)).length ? C.order.filter(id => !known.has(id)) : C.order)
  : C.order;
function showCard(){
  const pool = cardPool();
  C.i = ((C.i % pool.length) + pool.length) % pool.length;
  C.cur = pool[C.i]; const t = byId[C.cur];
  C.revealed = false;
  $('#c-cat').textContent = t.cat;
  $('#c-q').textContent = t.q;
  $('#c-a').innerHTML = '';
  $('#c-reveal').textContent = 'Reveal answer';
  $('#c-reveal').disabled = false;
  $('#c-count').textContent = `CARD ${String(C.i+1).padStart(2,'0')} / ${String(pool.length).padStart(2,'0')}`;
  syncKnownButtons();
}
function revealCard(){
  if (C.revealed) return;
  C.revealed = true;
  $('#c-a').innerHTML = renderMarkup(byId[C.cur].a);
  $('#c-reveal').textContent = 'Revealed';
  $('#c-reveal').disabled = true;
}

/* ---------- quiz ---------- */
const shuffle = a => { for(let i=a.length-1;i>0;i--){const j=(Math.random()*(i+1))|0; [a[i],a[j]]=[a[j],a[i]];} return a; };
const mod = (n,m) => ((n % m) + m) % m;
const Q = {mode:'mc', mc:[], mci:0, rc:[], rci:0, right:0, asked:0, flaggedOnly:false,
           answered:false, item:null, opts:[], correct:0, topic:null};

/* In multiple choice a flag belongs to the question; in recall there is no
   question, so it belongs to the topic. One set holds both. */
const flagKey = () => Q.mode === 'mc'
  ? (Q.item ? Q.item.id : null)
  : (Q.topic ? 'topic:' + Q.topic : null);

function syncFlag(){
  const k = flagKey(), on = k && flagged.has(k);
  const b = $('#q-flag');
  b.classList.toggle('on', !!on);
  b.setAttribute('aria-pressed', String(!!on));
  b.title = on ? 'Marked for review \u2014 click to clear' : 'Mark for review';
}
function toggleFlag(){
  const k = flagKey();
  if (!k) return;
  flagged.has(k) ? flagged.delete(k) : flagged.add(k);
  save(); syncFlag(); status(); paintTree(); syncFilter();
}
function syncFilter(){
  const n = Q.mc.filter(i => flagged.has(QUIZ[i].id)).length;
  $('#q-filter').textContent = Q.flaggedOnly
    ? `Flagged only (${n})` : `All questions${n ? ' \u00b7 ' + n + ' flagged' : ''}`;
  $('#q-filter').hidden = Q.mode !== 'mc';
}
const mcPool = () => {
  if (!Q.flaggedOnly) return Q.mc;
  const f = Q.mc.filter(i => flagged.has(QUIZ[i].id));
  return f.length ? f : Q.mc;
};
function locationHTML(item){
  const t = byId[item.t];
  if (!t) return '';
  const sec = item.sec
    ? ` <span class="arw">\u2192</span> ${esc(item.sec)}` : '';
  return `<div class="locate">Where to study this \u00b7 <b>#${String(t.n).padStart(2,'0')}</b> `
       + `${esc(t.cat)} <span class="arw">\u2192</span> <b>${esc(t.title)}</b>${sec}</div>`;
}

function quizScore(){
  const pct = Q.asked ? Math.round(100*Q.right/Q.asked) + '%' : '\u2014';
  $('#q-score').textContent = `SESSION  ${String(Q.right).padStart(2,'0')} / ${String(Q.asked).padStart(2,'0')}   \u00b7   ${pct}`;
}
function showQuiz(){ Q.mode === 'mc' ? showMC() : showRecall(); }

function showMC(){
  $('#q-opts').hidden = false; $('#q-recall').hidden = true;
  $('#q-check').hidden = true; $('#q-got').hidden = true; $('#q-miss').hidden = true;
  $('#q-topic').hidden = true; $('#q-a').innerHTML = ''; $('#q-explain').innerHTML = '';
  $('#q-locate').innerHTML = ''; $('#q-flag').hidden = false;
  $('#q-next').textContent = 'Next \u00a0\u2192';
  const pool = mcPool();
  Q.mci = mod(Q.mci, pool.length);
  const item = QUIZ[pool[Q.mci]];
  Q.item = item; Q.answered = false; Q.topic = item.t;
  const pairs = item.o.map((text, idx) => ({text, ok: idx === item.a}));
  shuffle(pairs);
  Q.opts = pairs; Q.correct = pairs.findIndex(p => p.ok);
  const t = byId[item.t];
  $('#q-cat').textContent = t ? t.cat : '';
  $('#q-q').textContent = item.q;
  $('#q-opts').innerHTML = pairs.map((p,i) =>
    `<button class="opt" data-i="${i}"><span class="k">${'ABCD'[i]}</span><span>${esc(p.text)}</span></button>`).join('');
  $('#q-opts').querySelectorAll('.opt').forEach(el =>
    el.onclick = () => answerMC(+el.dataset.i));
  syncFlag(); syncFilter(); quizScore();
}

function answerMC(pick){
  if (Q.answered) return;
  Q.answered = true;
  const ok = pick === Q.correct;
  Q.asked++; if (ok) Q.right++;
  if (ok) known.add(Q.topic); else known.delete(Q.topic);
  save(); status(); paintTree();
  $('#q-opts').querySelectorAll('.opt').forEach(el => {
    const i = +el.dataset.i;
    el.disabled = true;
    if (i === Q.correct) el.classList.add('correct');
    else if (i === pick) el.classList.add('wrong');
    else el.classList.add('dim');
  });
  $('#q-explain').innerHTML =
    `<div class="explain ${ok ? 'ok' : 'no'}"><div class="lead">${ok ? 'Correct' : 'Not quite'}</div>${inline(Q.item.why)}</div>`;
  $('#q-locate').innerHTML = locationHTML(Q.item);
  $('#q-topic').textContent = (Q.item.sec ? 'Read that section' : 'Read full topic') + ' \u00a0\u2192';
  $('#q-topic').hidden = false;
  if (!ok && !flagged.has(Q.item.id)){        // a miss is worth revisiting
    flagged.add(Q.item.id); save(); paintTree(); syncFilter();
  }
  syncFlag();
  quizScore();
}

function showRecall(){
  $('#q-opts').hidden = true; $('#q-opts').innerHTML = '';
  $('#q-recall').hidden = false; $('#q-flag').hidden = false;
  $('#q-explain').innerHTML = ''; $('#q-locate').innerHTML = '';
  $('#q-topic').hidden = true;
  $('#q-next').textContent = 'Skip \u00a0\u2192';
  Q.rci = mod(Q.rci, Q.rc.length);
  const t = byId[Q.rc[Q.rci]];
  Q.topic = t.id; Q.answered = false;
  $('#q-cat').textContent = t.cat;
  $('#q-q').textContent = t.q;
  const ta = $('#q-input'); ta.value = ''; ta.disabled = false;
  $('#q-a').innerHTML = '';
  $('#q-check').hidden = false; $('#q-check').textContent = 'Check answer'; $('#q-check').disabled = false;
  $('#q-got').hidden = true; $('#q-miss').hidden = true;
  $('#q-hint').textContent = 'Answer from memory, then check yourself.';
  syncFlag(); syncFilter(); quizScore();
}
function checkRecall(){
  if (Q.answered) return;
  Q.answered = true;
  $('#q-input').disabled = true;
  $('#q-a').innerHTML = renderMarkup(byId[Q.topic].a);
  $('#q-check').textContent = 'Answer shown'; $('#q-check').disabled = true;
  $('#q-hint').textContent = 'How did you do?';
  $('#q-got').hidden = false; $('#q-miss').hidden = false;
}
function gradeRecall(ok){
  Q.asked++; if (ok){ Q.right++; known.add(Q.topic); } else known.delete(Q.topic);
  save(); status(); paintTree(); Q.rci++; showRecall();
}
function nextQuiz(){ if (Q.mode === 'mc'){ Q.mci++; } else { Q.rci++; } showQuiz(); }
function setQuizMode(m){
  Q.mode = m;
  $('#q-mode').textContent = m === 'mc' ? 'Switch to recall' : 'Switch to multiple choice';
  showQuiz();
  syncFilter();
}

/* ---------- search ---------- */
function runSearch(){
  const q = $('#s-input').value.trim().toLowerCase();
  const hits = $('#s-hits');
  if (q.length < 2){ hits.innerHTML=''; $('#s-count').textContent='Type to search'; return; }
  const found = [];
  for (const t of TOPICS){
    const blob = (t.title+' '+t.q+' '+t.a+' '+t.cat).toLowerCase();
    if (blob.includes(q)){
      let score = blob.split(q).length - 1;
      if (t.title.toLowerCase().includes(q)) score += 30;
      if (t.q.toLowerCase().includes(q)) score += 15;
      found.push([score, t]);
    }
  }
  found.sort((a,b) => b[0]-a[0]);
  $('#s-count').textContent = found.length + (found.length===1 ? ' result' : ' results');
  hits.innerHTML = found.slice(0,60).map(([,t]) => {
    const ti = t.title.toLowerCase().indexOf(q);
    const title = ti >= 0
      ? esc(t.title.slice(0,ti)) + '<mark>' + esc(t.title.slice(ti,ti+q.length)) + '</mark>' + esc(t.title.slice(ti+q.length))
      : esc(t.title);
    return `<button class="hit" data-id="${t.id}"><div class="ht">${title}</div><div class="hc">${esc(t.cat)}</div></button>`;
  }).join('');
  hits.querySelectorAll('.hit').forEach(el => el.onclick = () => {
    const t = byId[el.dataset.id];
    $('#s-crumb').textContent = t.cat + '  \u2014  ' + t.title;
    $('#s-body').innerHTML = answerHTML(t);
    $('#v-search .pane .scroller').scrollTop = 0;
  });
}

/* ---------- modes ---------- */
function setMode(m){
  mode = m;
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v'+'-'+m));
  document.querySelectorAll('#nav button').forEach(b =>
    b.setAttribute('aria-current', String(b.dataset.mode === m)));
  if (m === 'search') setTimeout(() => $('#s-input').focus(), 40);
  status();
}

/* ---------- wiring ---------- */
function wire(){
  document.querySelectorAll('#nav button').forEach(b => b.onclick = () => setMode(b.dataset.mode));
  $('#b-known').onclick = () => toggleKnown(B.cur);
  $('#c-known').onclick = () => toggleKnown(C.cur);
  $('#c-reveal').onclick = revealCard;
  $('#c-next').onclick = () => { C.i++; showCard(); };
  $('#c-prev').onclick = () => { C.i--; showCard(); };
  $('#c-shuffle').onclick = () => { shuffle(C.order); C.i = 0; showCard(); };
  $('#c-filter').onclick = () => {
    C.unknownOnly = !C.unknownOnly;
    $('#c-filter').textContent = C.unknownOnly ? 'Unrevised only' : 'All topics';
    C.i = 0; showCard();
  };
  $('#q-check').onclick = checkRecall;
  $('#q-got').onclick = () => gradeRecall(true);
  $('#q-miss').onclick = () => gradeRecall(false);
  $('#q-next').onclick = nextQuiz;
  $('#q-mode').onclick = () => setQuizMode(Q.mode === 'mc' ? 'recall' : 'mc');
  $('#q-flag').onclick = toggleFlag;
  $('#q-filter').onclick = () => {
    Q.flaggedOnly = !Q.flaggedOnly; Q.mci = 0; showQuiz();
  };
  $('#q-topic').onclick = () => {
    setMode('browse');
    selectTopic(Q.topic, Q.item ? Q.item.sec : null);
  };
  $('#q-reset').onclick = () => {
    Q.right = Q.asked = Q.mci = Q.rci = 0;
    shuffle(Q.mc); shuffle(Q.rc); showQuiz();
  };
  $('#s-input').oninput = runSearch;

  $('#gear').onclick = () => $('#sheet').classList.toggle('on');
  $('#sheet-close').onclick = () => $('#sheet').classList.remove('on');
  $('#r-blur').oninput = e => { settings.blur = +e.target.value; applySettings(); save(); };
  $('#r-tint').oninput = e => { settings.tint = +e.target.value; applySettings(); save(); };
  $('#wp').onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    if (f.size > 16*1024*1024){ alert('That image is over 16 MB. Try a smaller one.'); return; }
    await api('/api/wallpaper', {method:'POST', headers:{'Content-Type': f.type || 'image/png'}, body: f});
    settings.wallpaper = true; settings.wpv = Date.now();
    applySettings(); save(); e.target.value = '';
  };
  $('#wp-clear').onclick = async () => {
    await api('/api/wallpaper', {method:'DELETE'});
    settings.wallpaper = false; applySettings(); save();
  };
  $('#reset-prog').onclick = () => {
    if (!confirm('Clear every "known" mark? This cannot be undone.')) return;
    known.clear(); save(); status(); paintTree(); syncKnownButtons();
  };
  $('#reset-flags').onclick = () => {
    if (!confirm('Clear every review flag? This cannot be undone.')) return;
    flagged.clear(); save(); status(); paintTree(); syncFlag(); syncFilter();
  };

  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (e.key === 'Escape'){ $('#sheet').classList.remove('on'); document.activeElement.blur(); return; }
    if (typing) return;
    if (e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))){ e.preventDefault(); setMode('search'); return; }
    if (['1','2','3','4'].includes(e.key)){ setMode(['browse','cards','quiz','search'][+e.key-1]); return; }
    if (mode === 'quiz' && Q.mode === 'mc'){
      const k = 'abcd'.indexOf(e.key.toLowerCase());
      if (k >= 0 && k < Q.opts.length && !Q.answered){ e.preventDefault(); answerMC(k); return; }
      if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); nextQuiz(); return; }
      if (e.key === 'f' || e.key === 'm'){ e.preventDefault(); toggleFlag(); return; }
    }
    if (mode === 'cards'){
      if (e.key === ' '){ e.preventDefault(); C.revealed ? (C.i++, showCard()) : revealCard(); }
      else if (e.key === 'ArrowRight'){ C.i++; showCard(); }
      else if (e.key === 'ArrowLeft'){ C.i--; showCard(); }
    }
  });
}

/* ---------- boot ---------- */
(async function init(){
  const [ts, qz, st] = await Promise.all([
    api('/api/topics').then(r => r.json()),
    api('/api/quiz').then(r => r.json()),
    api('/api/state').then(r => r.json()),
  ]);
  TOPICS = ts; QUIZ = qz; TOPICS.forEach(t => byId[t.id] = t);
  QUIZ.forEach(q => qById[q.id] = q);
  known = new Set((st.known || []).filter(k => byId[k]));
  flagged = new Set((st.flagged || []).filter(
    k => qById[k] || (k.startsWith('topic:') && byId[k.slice(6)])));
  settings = Object.assign(settings, st.settings || {});
  buildSwatches(); applySettings(); wire(); buildTree();
  C.order = TOPICS.map(t => t.id);
  Q.mc = shuffle(QUIZ.map((_, i) => i));
  Q.rc = shuffle(TOPICS.map(t => t.id));
  selectTopic(TOPICS[0].id); showCard(); showQuiz(); status();
})();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# Local server
# ----------------------------------------------------------------------------

WALLPAPER_PATH = os.path.join(os.path.expanduser("~"), ".fb_study_guide_wallpaper")
MAX_UPLOAD = 16 * 1024 * 1024


def load_state():
    try:
        with open(PROGRESS_PATH) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def write_state(d):
    try:
        with open(PROGRESS_PATH, "w") as f:
            json.dump(d, f, indent=1)
    except Exception:
        pass


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "FBStudyGuide/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass                      # keep the terminal clean

    # -- helpers ------------------------------------------------------------
    def _path(self):
        return urllib.parse.urlparse(self.path).path

    def _authed(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return qs.get("t", [None])[0] == self.server.token

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _deny(self):
        self._send(403, "forbidden", "text/plain")

    # -- routes -------------------------------------------------------------
    def do_GET(self):
        p = self._path()
        if p == "/":
            if not self._authed():
                return self._deny()
            page = HTML_PAGE.replace("__TOKEN__", self.server.token)
            return self._send(200, page, "text/html; charset=utf-8")
        if p == "/api/topics":
            if not self._authed():
                return self._deny()
            return self._json(TOPICS)
        if p == "/api/quiz":
            if not self._authed():
                return self._deny()
            return self._json(QUIZ)
        if p == "/api/state":
            if not self._authed():
                return self._deny()
            st = load_state()
            return self._json({"known": st.get("known", []),
                               "flagged": st.get("flagged", []),
                               "settings": st.get("settings", {})})
        if p == "/wallpaper":
            if not self._authed():
                return self._deny()
            try:
                with open(WALLPAPER_PATH, "rb") as f:
                    data = f.read()
            except Exception:
                return self._send(404, b"", "text/plain")
            st = load_state()
            ctype = st.get("settings", {}).get("wpmime", "image/png")
            return self._send(200, data, ctype)
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        p = self._path()
        if not self._authed():
            return self._deny()
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > MAX_UPLOAD:
            return self._send(413, "too large", "text/plain")
        body = self.rfile.read(n) if n else b""
        if p == "/api/state":
            try:
                incoming = json.loads(body.decode("utf-8"))
            except Exception:
                return self._json({"ok": False}, 400)
            st = load_state()
            st["known"] = sorted(set(incoming.get("known", [])))
            st["flagged"] = sorted(set(incoming.get("flagged", [])))
            merged = st.get("settings", {})
            merged.update(incoming.get("settings", {}))
            st["settings"] = merged
            write_state(st)
            return self._json({"ok": True})
        if p == "/api/wallpaper":
            try:
                with open(WALLPAPER_PATH, "wb") as f:
                    f.write(body)
            except Exception:
                return self._json({"ok": False}, 500)
            st = load_state()
            st.setdefault("settings", {})["wpmime"] = \
                self.headers.get("Content-Type", "image/png")
            write_state(st)
            return self._json({"ok": True})
        self._send(404, "not found", "text/plain")

    def do_DELETE(self):
        if not self._authed():
            return self._deny()
        if self._path() == "/api/wallpaper":
            try:
                os.remove(WALLPAPER_PATH)
            except Exception:
                pass
            return self._json({"ok": True})
        self._send(404, "not found", "text/plain")


def _app_browser():
    """A Chromium-family browser that supports --app= for a chromeless window."""
    if sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"]
        return next((c for c in cands if os.path.exists(c)), None)
    if sys.platform.startswith("win"):
        base = [os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                os.environ.get("LOCALAPPDATA", "")]
        rel = [r"Google\Chrome\Application\chrome.exe",
               r"Microsoft\Edge\Application\msedge.exe"]
        for b in base:
            for r in rel:
                p = os.path.join(b, r)
                if b and os.path.exists(p):
                    return p
        return None
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "microsoft-edge", "brave-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None


def launch(url):
    exe = _app_browser()
    if exe:
        try:
            subprocess.Popen(
                [exe, "--app=" + url, "--window-size=1280,860"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "app window"
        except Exception:
            pass
    try:
        webbrowser.open(url)
        return "browser tab"
    except Exception:
        return None


def run_web(port=0, open_browser=True):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.token = secrets.token_urlsafe(18)
    host, real_port = httpd.server_address
    url = "http://127.0.0.1:%d/?t=%s" % (real_port, httpd.token)

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("  FB Study Guide  \u00b7  %d topics" % len(TOPICS))
    print("  %s" % url)
    if open_browser:
        how = launch(url)
        if how:
            print("  opened in %s" % how)
        else:
            print("  couldn't open a browser \u2014 paste the URL above")
    print("  Ctrl-C to stop.\n")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        httpd.shutdown()


USAGE = """FB Study Guide

  python3 fb_study_guide.py              glass web UI (default)
  python3 fb_study_guide.py --tk         Tkinter fallback, no browser
  python3 fb_study_guide.py --no-browser print the URL, don't open anything
  python3 fb_study_guide.py --port 8777  pin the port
"""


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(USAGE)
        return
    if "--tk" in args or "--tkinter" in args:
        if not HAVE_TK:
            print("Tkinter isn't available in this Python build.\n"
                  "On macOS with Homebrew: brew install python-tk\n"
                  "Run without --tk to use the web UI instead.")
            return
        App().mainloop()
        return
    port = 0
    if "--port" in args:
        try:
            port = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            print("--port needs a number")
            return
    run_web(port=port, open_browser="--no-browser" not in args)


if __name__ == "__main__":
    main()
