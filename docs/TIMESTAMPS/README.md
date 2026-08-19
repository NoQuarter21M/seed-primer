# Pre-disclosure Timestamps

RFC 3161 cryptographic timestamps anchoring the SeedPrimer initial
public release to three independent timestamp authorities.

## What is timestamped

```
seed-primer
HEAD commit: 8a223f47de2cc4304bd3f02d2f53d84ee3655f95
Repository: https://github.com/NoQuarter21M/seed-primer
Timestamp request: 2026-08-19T20:16:22Z
```

The input file `timestamp_input.txt` was hashed by each TSA and
included in their signed timestamp token. This proves the repository
at this exact commit existed before each timestamp was issued.

## Timestamps

| Authority | Time (UTC) | Response file |
|---|---|---|
| FreeTSA (freetsa.org) | 2026-08-19 20:16:31 | timestamp_freetsa.tsr |
| DigiCert | 2026-08-19 20:16:40 | timestamp_digicert.tsr |
| Sectigo | 2026-08-19 20:16:47 | timestamp_sectigo.tsr |

All three verified OK against the system CA bundle and FreeTSA's
published root certificate.

## Verification

```bash
# FreeTSA
curl -s https://freetsa.org/files/cacert.pem -o freetsa_ca.pem
openssl ts -verify -in timestamp_freetsa.tsr \
  -data timestamp_input.txt \
  -CAfile freetsa_ca.pem

# DigiCert / Sectigo (use system CA bundle)
openssl ts -verify -in timestamp_digicert.tsr \
  -data timestamp_input.txt \
  -CAfile /etc/ssl/certs/ca-certificates.crt

openssl ts -verify -in timestamp_sectigo.tsr \
  -data timestamp_input.txt \
  -CAfile /etc/ssl/certs/ca-certificates.crt
```

Expected output for each: `Verification: OK`

## Standard

RFC 3161 — Internet X.509 Public Key Infrastructure Time-Stamp
Protocol (TSP). Each .tsr file is a DER-encoded TimeStampResponse
containing a signed TimeStampToken from the issuing TSA.

## Purpose

Pre-disclosure timestamping establishes that the SeedPrimer codebase
existed in its current form before public release. Three independent
TSAs are used as a quorum — no single authority can retroactively
alter or deny the timestamp.
