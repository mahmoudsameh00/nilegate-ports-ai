### Final Checkpoint — what was done, what went wrong, how it was fixed

| Phase | What | Problem found | Fix / consequence |
|---|---|---|---|
| 1 | Read containers, vessels, invoices, ports (read-only), the AIS voyages and the IFTMIN template | Every container shares its vessel's origin and destination | One consignment group per vessel: 434 messages for 1,000 containers. |
| 2 | Build messages on the template | The template has no IMO and no voyage; PostgreSQL has no weights or seals; the sample's `UNT` count was wrong | IMO + voyage in `TDT`, dates from the AIS voyage, `UNT` computed; weights and seals are seeded documented defaults; text escaped with the release character; `RFF+IV` = the vessel's latest invoice (owner decision 2026-09-28: the flow is mimicked, dates are not aligned). |
| 3 | Round trip + consistency | The first template-order check failed on 24 messages whose containers are all empty (no `SEL` by rule) | The check treats `SEL` as conditional; round trip, envelope, IMO/LOCODE/container consistency and AIS voyage match all pass; no `MOA` (D14); every invoice reference belongs to the message's vessel (376 messages). |
| 4 | Save + reload | — | `edi_messages_synthetic.jsonl` (434 lines) + manifest; byte hash reviewed. |
