# Upstream SEC submission fixture

`0000943374-24-000509.txt` is copied byte-for-byte from `data/sgml/0000943374-24-000509.txt` in dgunning/edgartools@v5.62.1 `9f2ff388c0ad21cfbaba4c7587ba8be7abe6816d`, read 2026-11-06. SHA-256: `521de6ce26894f75f215215cbea9746932d5093908bfc45688b93e10cf43f394` (161,378 bytes).

This is the upstream test corpus's archived 1895 Bancorp 8-K submission, accession `0000943374-24-000509`, CIK `1847360`. Its header acceptance is `20241227162940`; a local receipt and point-in-time availability are unknown. The SEC archive URL corresponding to that identity is `https://www.sec.gov/Archives/edgar/data/1847360/000094337424000509/0000943374-24-000509.txt`; it was not fetched by this task. Existing notices inside the filing remain verbatim. `EDGARTOOLS-LICENSE.txt` carries the upstream repository's MIT notice.

The negative proof removes only the acceptance line in memory and never rewrites these bytes. Transport tests use a reserved `.invalid` fixture identity with sockets denied; it is never a real SEC contact or data/tuning authority. No corporate event is assigned a polarity or converted into an order.
