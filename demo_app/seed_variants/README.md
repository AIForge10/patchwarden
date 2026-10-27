# Seeded demo variants

The default checkout app deliberately returns an unrecognised gateway payload in
`malformed` mode. `test_incident.py` therefore fails on the pinned baseline; it
is the authorized reproducer for `demo-001`, not a passing regression test.

The normal and decline paths are covered by `test_baseline.py`. The discovery
catalog uses those deterministic modes as its trusted negative-control surface.

`control/` is an independent, known-good gateway implementation. Its dedicated
test guards the negative control required by discovery evaluation, so it must not
be changed by a candidate repair.
