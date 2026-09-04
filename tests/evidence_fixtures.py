"""Hand-constructed ClaimEvidence fixtures for engine tests.

These mirror what live Gemini extraction returns for the sample claims
(CLM-001/002/007 were modelled directly on real extraction output), but are
fully deterministic and offline. The engine must reach its decisions from this
evidence plus the policy — fixtures contain no decisions or expectations.
"""

from __future__ import annotations

from claimiq.extraction.schemas import ClaimEvidence, DocumentFacts

MODEL = "fixture-model"


def F(value, quote="", verified=True):
    return {"value": value, "quote": quote, "quote_verified": verified}


def _evidence(claim_id: str, docs: dict[str, dict]) -> ClaimEvidence:
    ev = ClaimEvidence(claim_id=claim_id, model=MODEL)
    for doc_type, fields in docs.items():
        ev.documents[doc_type] = DocumentFacts.model_validate(fields)
    return ev


_BUILDERS = {}


def _register(claim_id):
    def wrap(fn):
        _BUILDERS[claim_id] = fn
        return fn
    return wrap


def evidence_for(claim_id: str) -> ClaimEvidence:
    return _BUILDERS[claim_id]()


@_register("CLM-001")
def _clm001() -> ClaimEvidence:
    return _evidence("CLM-001", {
        "claim_form": {
            "claim_type": F("accident", "[X] Accident Damage"),
            "policyholder_name": F("ROHAN MALHOTRA", "Name of Insured: ROHAN MALHOTRA"),
            "vehicle_registration": F("MH12QT4431", "Vehicle Reg. No: MH 12 QT 4431"),
            "incident_date": F("2026-01-10", "Date of Accident: 10/01/2026"),
            "driver_name": F("ROHAN MALHOTRA", "Who was driving at the time: SELF"),
            "driver_is_policyholder": F(True, "Who was driving at the time: SELF"),
            "driver_licence_number": F("MH12 20190041123", "Driving Licence No: MH12 20190041123"),
            "claimed_amount": F(8450, "Estimated repair cost: Rs. 8,450/-"),
            "damage_description": F("Bike skidded and hit the road divider; front damage",
                                    "hit the road divider"),
            "document_date": F("2026-01-13", "Date: 13/01/2026"),
        },
        "repair_estimate": {
            "policyholder_name": F("Rohan Malhotra", "Customer: Rohan Malhotra"),
            "vehicle_registration": F("MH12QT4431", "Reg no MH12QT4431"),
            "claimed_amount": F(8450, "TOTAL: Rs. 8,450/-"),
            "damage_description": F("Front mudguard, headlamp, handlebar, fork",
                                    "Work required (accident damage - front)"),
            "document_date": F("2026-01-12", "Date: 12/01/2026"),
        },
        "incident_description": {
            "claim_type": F("accident", "accident with my bike"),
            "policyholder_name": F("Rohan Malhotra", "Rohan Malhotra"),
            "vehicle_registration": F("MH12QT4431", "MH12QT4431"),
            "incident_date": F("2026-01-10", "On the evening of 10th Jan 2026"),
            "driver_name": F("Rohan Malhotra", "I was riding home", verified=False),
            "claimed_amount": F(8450, "Rs 8,450"),
            "vehicle_received_at_garage_date": F("2026-01-12", "Sunday (12th)"),
            "damage_description": F("mudguard, headlight, handle bent, fork out of alignment",
                                    "The front of the bike is damaged"),
        },
    })


@_register("CLM-002")
def _clm002() -> ClaimEvidence:
    return _evidence("CLM-002", {
        "claim_form": {
            "claim_type": F("accident", "[X] Accident Damage"),
            "policyholder_name": F("Arjun Mehta", "Name of Insured: Arjun Mehta"),
            "vehicle_registration": F("DL8CAF5027", "Vehicle Reg. No: DL8CAF5027"),
            "incident_date": F("2026-02-18", "Date of Accident: 18/02/2026"),
            "driver_name": F("Arjun Mehta", "Who was driving at the time: SELF"),
            "driver_is_policyholder": F(True, "Who was driving at the time: SELF"),
            "driver_licence_number": F("DL-0420180099231", "Driving Licence No: DL-0420180099231"),
            "claimed_amount": F(62000, "Estimated repair cost: Rs. 62,000/-"),
            "damage_description": F("left side scraped against the road divider",
                                    "scraped against the road divider"),
        },
        "repair_estimate": {
            "policyholder_name": F("Mr Arjun Mehta", "Customer name: Mr Arjun Mehta"),
            "vehicle_registration": F("DL8CAF5072", "Regn: DL 8C AF 5072"),
            "claimed_amount": F(62000, "ESTIMATE TOTAL: Rs. 62,000/-"),
            "vehicle_received_at_garage_date": F("2026-02-15", "Vehicle received on: 15/02/2026"),
            "damage_description": F("Front bumper cracked, LH fender bent, LH headlamp broken",
                                    "Damage observed"),
        },
        "incident_description": {
            "policyholder_name": F("Arjun Mehta", "Arjun Mehta, policy NMS-PC-208915"),
            "incident_date": F("2026-02-14", "On the evening of 14th February 2026"),
            "driver_name": F("Karan Mehta", "my brother Karan Mehta was driving"),
            "driver_is_policyholder": F(False, "my brother Karan Mehta was driving and I was in the passenger seat"),
            "vehicle_received_at_garage_date": F("2026-02-15", "Next day we sent the car to Capital Motors"),
            "damage_description": F("left side badly scratched, front left damaged",
                                    "the left side is badly scratched"),
        },
    })


@_register("CLM-003")
def _clm003() -> ClaimEvidence:
    return _evidence("CLM-003", {
        "claim_form": {
            "claim_type": F("accident", "[X] Accident Damage"),
            "policyholder_name": F("Sana Qureshi", "Name of Insured: Sana Qureshi"),
            "vehicle_registration": F("KA05MN7788", "Vehicle Reg. No: KA 05 MN 7788"),
            "incident_date": F("2026-03-02", "Date of Accident: 02/03/2026"),
            "driver_name": F("Sana Qureshi", "Who was driving at the time: Self"),
            "driver_is_policyholder": F(True, "Who was driving at the time: Self"),
            "driver_licence_number": F("KA05 20200155803", "Driving Licence No: KA05 20200155803"),
            "claimed_amount_note": F("(to follow - awaiting garage estimate)",
                                     "Estimated repair cost: (to follow - awaiting garage estimate)"),
            "damage_description": F("Rear bumper and tail lamp damaged",
                                    "Rear bumper and tail lamp damaged"),
        },
        "incident_description": {
            "policyholder_name": F("Sana Qureshi", "Sana Qureshi"),
            "vehicle_registration": F("KA05MN7788", "my i20 (KA05MN7788)"),
            "incident_date": F("2026-03-02", "On 2nd March evening"),
            "damage_description": F("rear bumper deep scrape and cracked; tail lamp broken",
                                    "The rear bumper has a deep scrape"),
        },
    })


@_register("CLM-004")
def _clm004() -> ClaimEvidence:
    return _evidence("CLM-004", {
        "claim_form": {
            "claim_type": F("accident", "[X] Accident Damage"),
            "policyholder_name": F("Devraj Kulkarni", "Name of Insured: Devraj Kulkarni"),
            "vehicle_registration": F("KA03HF2210", "Vehicle Reg. No: KA03HF2210"),
            "incident_date": F("2026-02-21", "Date of Accident: 21/02/2026"),
            "driver_name": F("Devraj Kulkarni", "Who was driving at the time: Self"),
            "driver_is_policyholder": F(True, "Who was driving at the time: Self"),
            "driver_licence_number": F("KA03 20150087661", "Driving Licence No: KA03 20150087661"),
            "claimed_amount": F(38700, "Estimated repair cost: Rs. 38,700/-"),
            "damage_description": F("Front and right side of the bike damaged",
                                    "hit the metal road barrier"),
        },
        "repair_estimate": {
            "policyholder_name": F("DEVRAJ KULKARNI", "CUSTOMER: DEVRAJ KULKARNI"),
            "vehicle_registration": F("KA03HF2210", "REG KA 03 HF 2210"),
            "claimed_amount": F(38700, "TOTAL ESTIMATE: RS. 38,700/-"),
            "damage_description": F("Fuel tank dented, front fork bent, headlamp broken",
                                    "ACCIDENT DAMAGE - FRONT & RH SIDE"),
        },
        "incident_description": {
            "policyholder_name": F("Devraj Kulkarni", "Devraj Kulkarni"),
            "vehicle_registration": F("KA03HF2210", "claim for KA03HF2210"),
            "incident_date": F("2026-02-21", "On Saturday 21st Feb night"),
            "damage_description": F("tank dented, front fork bent, headlamp broke",
                                    "The bike's tank got dented"),
            "risk_mentions": [{
                "risk_type": "alcohol_or_drugs",
                "quote": "I had two-three drinks at the reception over the evening but I was feeling fine to ride.",
                "quote_verified": True,
            }],
        },
    })


@_register("CLM-005")
def _clm005() -> ClaimEvidence:
    return _evidence("CLM-005", {
        "claim_form": {
            "claim_type": F("accident", "[X] Accident Damage"),
            "policyholder_name": F("Meera Pillai", "Name of Insured: Meera Pillai"),
            "vehicle_registration": F("TN10BX3391", "Vehicle Reg. No: TN 10 BX 3391"),
            "incident_date": F("2026-04-03", "Date of Accident: 03/04/2026"),
            "driver_name": F("Meera Pillai", "Who was driving at the time: Self"),
            "driver_is_policyholder": F(True, "Who was driving at the time: Self"),
            "driver_licence_number": F("TN10 20170233916", "Driving Licence No: TN10 20170233916"),
            "claimed_amount": F(54300, "Estimated repair cost: Rs. 54,300/-"),
            "damage_description": F("Rear bumper, tailgate and right tail lamp damaged",
                                    "Rear bumper, tailgate and right tail lamp damaged"),
        },
        "repair_estimate": {
            "policyholder_name": F("Ms. Meera Pillai", "Customer: Ms. Meera Pillai"),
            "vehicle_registration": F("TN10BX3391", "Reg. TN10BX3391"),
            "claimed_amount": F(54300, "TOTAL: Rs. 54,300/-"),
            "damage_description": F("Rear impact damage", "Rear impact damage"),
            "document_date": F("2026-04-26", "Date: 26/04/2026"),
        },
        "incident_description": {
            "policyholder_name": F("Meera Pillai", "Meera Pillai"),
            "vehicle_registration": F("TN10BX3391", "my Nexon (TN10BX3391)"),
            "incident_date": F("2026-04-03", "On 3rd April 2026 evening"),
            "damage_description": F("rear bumper cracked, boot door dented, tail light broke",
                                    "The rear bumper cracked"),
        },
    })


@_register("CLM-006")
def _clm006() -> ClaimEvidence:
    return _evidence("CLM-006", {
        "claim_form": {
            "claim_type": F("accident", "[X] Accident Damage"),
            "policyholder_name": F("Farhan Ansari", "Name of Insured: Farhan Ansari"),
            "vehicle_registration": F("MH04GT0092", "Vehicle Reg. No: MH 04 GT 0092"),
            "incident_date": F("2026-06-08", "Date of Accident: 08/06/2026"),
            "driver_name": F("Farhan Ansari", "Who was driving at the time: Self"),
            "driver_is_policyholder": F(True, "Who was driving at the time: Self"),
            "driver_licence_number": F("MH04 20120019442", "Driving Licence No: MH04 20120019442"),
            "claimed_amount": F(385600, "Estimated repair cost: Rs. 3,85,600/-"),
            "damage_description": F("Severe damage to front of car",
                                    "went partly under the rear of the truck"),
        },
        "repair_estimate": {
            "policyholder_name": F("Farhan Ansari", "Customer: Farhan Ansari"),
            "vehicle_registration": F("MH04GT0092", "Regn MH04GT0092"),
            "claimed_amount": F(385600, "ESTIMATE TOTAL: Rs. 3,85,600/-"),
            "vehicle_received_at_garage_date": F("2026-06-08", "Vehicle towed in on 08/06/2026"),
            "damage_description": F("Front-end collision damage, heavy structural damage",
                                    "Heavy structural damage to front"),
        },
        "incident_description": {
            "policyholder_name": F("Farhan Ansari", "Statement of Farhan Ansari"),
            "vehicle_registration": F("MH04GT0092", "claim for MH04GT0092"),
            "incident_date": F("2026-06-08", "On 8th June 2026 morning"),
            "damage_description": F("bonnet and front crushed, both airbags opened",
                                    "The bonnet and front portion got crushed"),
        },
    })


@_register("CLM-007")
def _clm007() -> ClaimEvidence:
    return _evidence("CLM-007", {
        "claim_form": {
            "claim_type": F("theft", "[X] Theft"),
            "policyholder_name": F("Nikhil Rao", "Name of Insured: Nikhil Rao"),
            "vehicle_registration": F("TS09EQ5566", "Vehicle Reg. No: TS 09 EQ 5566"),
            "incident_date": F("2026-05-08", "Date/Time vehicle last seen: 08/05/2026"),
            "discovered_date": F("2026-05-09", "Date/Time theft discovered: 09/05/2026, around 7:30 AM"),
            "fir_number": F("0187/2026", "FIR No: 0187/2026"),
            "fir_date": F("2026-05-09", "Date of FIR: 09/05/2026"),
            "police_station": F("Madhapur PS, Cyberabad", "Police Station: Madhapur PS, Cyberabad"),
            "claimed_amount_note": F("As per IDV / declared value", "Claimed amount: As per IDV / declared value"),
            "vehicle_itself_stolen": F(True, "Next morning it was not there"),
        },
        "fir": {
            "claim_type": F("theft", "Section 303(2) BNS (Theft)"),
            "policyholder_name": F("Nikhil Rao", "Complainant: Nikhil Rao"),
            "vehicle_registration": F("TS09EQ5566", "Regn No. TS09EQ5566"),
            "incident_date": F("2026-05-08", "on the night of 08/05/2026 at about 2200 hrs"),
            "discovered_date": F("2026-05-09", "On 09/05/2026 at about 0730 hrs"),
            "fir_number": F("0187/2026", "FIR No: 0187/2026"),
            "fir_date": F("2026-05-09", "Date: 09/05/2026"),
            "vehicle_itself_stolen": F(True, "the vehicle was found missing"),
        },
        "incident_description": {
            "claim_type": F("theft", "theft claim for my Activa"),
            "policyholder_name": F("Nikhil Rao", "Nikhil Rao"),
            "vehicle_registration": F("TS09EQ5566", "Activa TS09EQ5566"),
            "incident_date": F("2026-05-08", "on 8th May around 10 pm"),
            "discovered_date": F("2026-05-09", "On 9th morning around 7:30"),
            "fir_number": F("0187/2026", "FIR (no. 0187/2026)"),
            "vehicle_itself_stolen": F(True, "the scooter was not in its place"),
        },
    })


@_register("CLM-008")
def _clm008() -> ClaimEvidence:
    return _evidence("CLM-008", {
        "claim_form": {
            "claim_type": F("theft", "[X] Theft"),
            "policyholder_name": F("Tanvi Joshi", "Name of Insured: Tanvi Joshi"),
            "vehicle_registration": F("GJ01RV8123", "Vehicle Reg. No: GJ 01 RV 8123"),
            "incident_date": F("2026-07-19", "Date of Incident: 19/07/2026"),
            "discovered_date": F("2026-07-19", "between 6:15 PM and 9:00 PM"),
            "fir_number": F("445/2026", "e-complaint No. 445/2026"),
            "claimed_amount": F(124000, "Claimed amount: Rs. 1,24,000/-"),
            "stolen_items": F("office laptop (Dell Latitude) and bag with documents and accessories",
                              "My office laptop (Dell Latitude, approx value Rs. 1,10,000) and bag"),
            "vehicle_itself_stolen": F(False, "The car itself was not taken and has no damage"),
        },
        "fir": {
            "policyholder_name": F("Tanvi Joshi", "Complainant: Tanvi Joshi"),
            "vehicle_registration": F("GJ01RV8123", "Regn GJ01RV8123"),
            "incident_date": F("2026-07-19", "on 19/07/2026 she parked her Kia Sonet"),
            "discovered_date": F("2026-07-19", "On returning at about 2100 hrs she found"),
            "fir_number": F("445/2026", "Complaint No: 445/2026"),
            "fir_date": F("2026-07-20", "Date of Registration: 20/07/2026"),
            "stolen_items": F("Dell Latitude laptop, charger, documents, personal items",
                              "The bag contained one Dell Latitude laptop"),
            "vehicle_itself_stolen": F(False, "The car was found parked in the same place"),
        },
        "incident_description": {
            "policyholder_name": F("Tanvi Joshi", "Tanvi Joshi"),
            "vehicle_registration": F("GJ01RV8123", "my car GJ01RV8123"),
            "incident_date": F("2026-07-19", "On 19th July evening"),
            "discovered_date": F("2026-07-19", "When I came back around 9 pm"),
            "stolen_items": F("laptop bag with office laptop", "my laptop bag which I had kept on the back seat was gone"),
            "vehicle_itself_stolen": F(False, "The car itself is absolutely fine and with me"),
            "risk_mentions": [{
                "risk_type": "vehicle_left_unlocked_or_keys_inside",
                "quote": "Honestly I am not 100% sure if I locked it",
                "quote_verified": True,
            }],
        },
    })
