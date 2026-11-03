# config_fan_control

Fan control by **normalised per-component thermal demand**. Each sensor is normalised to a
0–100 demand against **its own** limits; each fan group follows the **worst** of the sensors it
cares about.

## Why this exists rather than a hardware curve

The Super-I/O chip can only steer its curves off **its own** `temp1-13` channels. `amdgpu`,
`nvme` and `k10temp` are separate chips, invisible to it — so "case fans respond to GPU junction
temperature" is outside what the hardware can express at all.

Anything the chip **can** do belongs in the chip's own curve, where no userspace process sits in
the thermal path. This daemon is only for what the hardware cannot do.

## Onboarding a new machine

**Start with discovery.** It surveys the thermal hardware and writes a draft inventory block:

```bash
# a play that includes this role with tasks_from: discover, setting fand_discover_output
# -> the draft at fand_discover_output (paste into inventory once edited)
```

It reads every hwmon chip, proposes a sensor per usable channel with floor/ceiling/gamma, and
anchors each ceiling to the **hardware's own declared limits** where it has them. It also
disambiguates same-named chips by PCI path and gives colliding sensor names a unique suffix —
without which a machine's iGPU can masquerade as its discrete card.

**It proposes; it does not decide.** Three things no sensor can report, so it refuses to guess:

| Unknown | How the draft handles it | How to resolve it |
|---|---|---|
| which header drives which fan | groups emitted **commented out** | hold one header at a time at a fixed duty, and listen |
| which header is a **pump** | `fand_pump_headers: []` with a warning | BIOS fan page names them (`AIO_PUMP`); highest steady RPM + flat curve is the tell |
| what is audible | `pwm_min`/`pwm_max` placeholders | a duty sweep per header measures stall and noise |

A draft that looked finished would be worse than one that obviously is not — so a careless
paste yields a config with no fan groups, which does nothing, rather than one that drives a pump.

### The full flow

1. **Discover** — the `discover` entrypoint, above.
2. **Identify the pump** before anything else. Getting this wrong is the one genuinely dangerous
   mistake here.
3. **Map headers to fans** — hold one header at a fixed duty at a duty so you can hear
   which fans changed. Quiet the other headers first or the loud ones mask everything.
4. **Measure stall and noise** — sweep each header's duty and record RPM. Stall is often a step function rather
   than a gradual fade, so `pwm_min` wants clearance, not the exact edge.
5. **Paste the edited block** into the host's inventory entry.
6. **Validate without applying** — the role reports and stops unless `fand_apply=true`.
7. **Apply**, then prove the safety contract with a kill test (below).

## Reuse on another machine

**Inventory block, no code change.** The role carries the mechanism; inventory carries every
machine-specific fact. An illustrative block (chip, headers and PCI path are examples):

```yaml
fand_chip: nct6799
fand_pump_headers: [7]        # REFUSED outright — a pump is not a fan
fand_sensors:
  - name: gpu_junction
    chip: amdgpu
    label: junction
    path_contains: "0000:03:00.0"   # with two amdgpu chips (iGPU + dGPU), disambiguate or it refuses
    floor: 45
    ceiling: 100                    # hardware crit is 110 — asserted against, not trusted
    gamma: 1.6                      # >1: flat low, hard ramp near the top
fand_groups:
  - name: case
    header: 2
    chip: nct6799
    sensors: [gpu_junction, cpu_tctl, nvme_composite]
    pwm_min: 51                     # must clear the fans' measured stall duty
    pwm_max: 191
```

`fand_sensors`, `fand_groups` and `fand_chip` are **required with no default**: a role cannot
know what sensors a machine has, and a default would be wrong everywhere else while looking
authoritative.

## Safety

| Mechanism | Covers |
|---|---|
| `ExecStop` | clean shutdown |
| `ExecStopPost` → `fand-release` | **crash, SIGKILL, OOM** — runs when `ExecStop` did not |
| `WatchdogSec` | hung-but-alive, which neither of the above fires for |
| daemon's own `finally` | normal exit and caught signals |

All four converge on the same outcome: **the headers return to the hardware curve.** Losing the
daemon must never leave a fan pinned at a last write.

Verify it with a kill test: SIGKILL the main process and assert the headers come back unaided.
That test is what exposes the two failure modes below.

Also:

- **Refuses to start on an unresolved sensor.** A missing sensor must not silently drop out of
  the max: that would lower fan speed exactly when something is unmonitored.
- **Refuses a ceiling above the hardware's own `crit`.** Read from `temp*_crit`/`_max` at startup
  and asserted, so a typo cannot delay full speed past the vendor's critical temperature.
- **Refuses two same-named chips with no `path_contains`.** A board with an iGPU and a discrete
  card has two `amdgpu`; picking one arbitrarily could silently read the iGPU instead of the discrete card.
- **Refuses a group targeting a pump header** — cavitation and loss of coolant flow.
- **Fail-safe on sensor loss**: release to the hardware curve *and* raise its floor points. The
  chip's curve only follows CPU temperature, so a lost GPU sensor would otherwise let it run
  quiet while the GPU cooks.

## Two failure modes the kill test guards against

**`ExecStopPost` written with shell `\` continuations.** systemd does not process them, so
the command arrives malformed, and a `-` prefix makes it fail *silently*. Hence a real script
(`files/fand-release`) that can be tested on its own, with no `-` prefix so a failure is visible.

**The deadband masked a lost header.** `applied` is read back from the pwm *duty* register, which
holds a value in automatic mode too. After a release, the chip's own duty can sit within the
deadband of the last applied duty, so the comparison says "no change needed" and the header is
never retaken — the daemon runs with fresh metrics and a healthy loop while the hardware drives
the fans. **The mode is the authority on who is in control, never the duty.**

## Testing

```bash
python3 roles/config_fan_control/files/test_fand.py   # no hardware needed
```

Every refusal is proven to **fire**, not merely to be present.

## Observability

- **Prometheus textfile** at `fand_metrics_path`, written atomically each loop. Costs nothing on
  a host with no scraper; collected the moment Alloy's unix exporter appears, with no change here.
- **journald** for events — resolution, fail-safe entry/exit, refusals.

`fand_group_driving_demand` names **which sensor** is driving each group. That is the point:
"GPU mem at 82%" is actionable, "fans at 60%" is not.
