# Aircraft Home-Base Intelligence

**What can be deduced about each craft's operator, owner, and mission purely from
where it takes off and — above all — where it lands and stays?** And once every
craft's home base is known, what do the *shared* locations tell us?

This is the analytical product of `pipeline/home_base_correlation.py`. Run it live with:

```bash
python run_all.py --home-base C6062        # one craft
python run_all.py --fleet-correlation      # the whole fleet + shared-space leads
python run_all.py --export-home-base ./outputs/home_base
```

## Why the resting spot is the strongest single signal

Altitude, speed, and duration describe *what a craft is doing on a given sortie*.
The place it parks overnight describes *who owns it*. Facilities have operators,
and an aircraft that consistently sleeps at a facility almost always belongs to —
or is contracted by — that operator. So the method is:

1. Collect every takeoff (`origin_lat/lon`) and landing (`dest_lat/lon`) for a callsign.
2. Cluster them by proximity (~2 nm). Weight the **first event of each local day**
   and the **last event of each local day** more heavily — those are the moments the
   craft was demonstrably parked overnight (the "final resting spot").
3. Map the dominant cluster to the nearest **operator-bearing** facility in the
   Puerto Rico infrastructure graph (`pipeline/gis_intelligence.py`), preferring a
   distinctive operator (USCG, PREPA, PR Police, US Navy) over a generic field (FAA / port).
4. Fuse that with the `KNOWN_OPERATORS` registry: the home base either **corroborates**
   the registry, or **conflicts** with it (a lead worth flagging — detachment, lease,
   or shared apron).

## Per-craft deduction (the four documented craft)

| Callsign | Final resting spot | Facility operator | → Owner | → Mission | Confidence |
|----------|--------------------|-------------------|---------|-----------|------------|
| **C6062** | USCG Air Station Borinquen (NW, ≈18.49,-67.13) | USCG | United States Coast Guard | Search & Rescue / Maritime Patrol | High — base **corroborates** registry |
| **N5854Z** | Isla Grande / Palo Seco (PREPA) | PREPA (Palo Seco) / civil hub (Isla Grande) | PR Electric Power Authority | Power Line Inspection | High — registry + PREPA substation |
| **N767PD** | FURA base, San Juan metro (≈18.45,-66.05) | Puerto Rico Police | PR Police Department (FURA) | Law Enforcement | High — base **corroborates** registry |
| **N684JB** | Isla Grande GA apron (≈18.452,-66.120) | FAA (civil field) | Private owner | Private Charter | Medium — civil field, no state operator |

Reading of each:

- **C6062 — federal, and physically segregated.** Its resting spot is the rotary-wing
  pad co-located with Rafael Hernández / Aguadilla in the far northwest. That field is
  USCG Air Station Borinquen, so the location *alone* yields owner = US Coast Guard and a
  SAR / maritime-patrol mission — and the `C`-prefix registry agrees. It is the only craft
  that beds down outside the San Juan metro.
- **N5854Z — PREPA.** When it rests at the Palo Seco generation complex (a PREPA-operated
  substation), the location resolves straight to the power utility and a line-inspection
  mission. When it instead stages from the Isla Grande civil hub, the *location alone* is
  ambiguous (a shared field) and the operator identity is carried by the registry — the
  honest limit of the location signal.
- **N767PD — FURA.** Its resting spot is the San Juan police tactical base, which is an
  operator-bearing facility, so the location independently confirms PR Police / law
  enforcement.
- **N684JB — private.** It rests on the Isla Grande general-aviation apron. That field's
  operator is the FAA, i.e. *no* state operator — exactly what you expect of a private /
  charter craft. The location tells you "civil," and nothing more, which is itself the
  finding.

## Using all four together — shared-space leads

Plotting the four home bases against each other (the `--fleet-correlation` product):

- **Isla Grande (SIG) is a shared apron.** PREPA's N5854Z and the private N684JB both
  bed down here. Shared apron ⇒ shared fuel, maintenance, and ATC relationships and a
  common operating tempo. This clusters them as **San Juan civil/territorial rotorcraft**
  and is the single clearest cross-craft lead: an unknown craft later found resting at
  Isla Grande inherits this civil-hub context by default.
- **The San Juan metro is the territorial centre of gravity.** Three of the four
  (N5854Z, N684JB, N767PD) rest within the metro; FURA's base sits a few nautical miles
  east of the Isla Grande apron — distinct facilities, one operating region.
- **C6062 is the outlier.** It is the only craft anchored in the northwest, at a federal
  installation, with no apron-sharing partner. Geographic isolation + a federal facility =
  a different chain of command from the rest of the fleet. If a second craft ever resolves
  to Borinquen, that co-location is immediately a high-value lead (a USCG detachment partner).

### Lead logic going forward
- **Same base, same operator** → confirms an operator's fleet and tempo.
- **Same base, different operators** → flag: shared facility / joint operations / contract relationship.
- **A craft alone at a state/federal base** → strong, registry-independent operator attribution.
- **A craft at an FAA/port field** → "civil"; defer operator identity to the registry or further signals.

## Confidence & limits

- The location signal is strongest for craft that rest at an **operator-bearing** facility
  (USCG/PREPA/police/navy). At generic FAA fields it yields "civil" and no more.
- Home bases are derived from FR24-extracted coordinates; clustering tolerates ~2 nm of OCR /
  georeferencing error, and overnight weighting guards against a busy outstation being mistaken
  for the home base.
- With no flight database present, the report still renders for the four known craft from their
  canonical base coordinates, so the analysis degrades gracefully.
