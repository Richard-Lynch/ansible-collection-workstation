# rpi_fleet_report

READ-ONLY drift report across the Pi fleet: boot device, EEPROM order, rescue-card sealing,
watchdog, throttling, and whether each node is still actually stateless.

Exists so drift is found **on purpose**, on a schedule, rather than during an incident: state
that nothing reports keeps drifting until the moment it matters.

## Usage

```bash
ansible-playbook fleet_report.yml
# CI / scheduled: turn drift into a failure
ansible-playbook fleet_report.yml -e rpi_report_fail_on_drift=true
```

## The two checks that earn their keep

**Boot source.** A Pi that has silently fallen back to its rescue card behaves completely normally:
it answers SSH, serves its workload, reports healthy. It is running on a card that was never meant
to carry a workload and will wear out, and nothing else on the network will say so.

**Statelessness.** The entire recovery story is "Ansible is the backup" — true only for as long as
nothing important lives outside the repo. Docker volumes and hand-seeded tokens are state
regardless of how a service was deployed, so the assumption is **checked** rather than asserted once
and trusted for a year. When this starts reporting real state, that is the signal to do the backup
work — driven by evidence rather than a calendar.

## Inputs

See `meta/argument_specs.yml` (generated — edit `meta/argument_specs.py`).
