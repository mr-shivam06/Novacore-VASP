"""Bounded Bitcoin tracing with prioritized payment paths and VASP attribution."""



from collections import deque



from .heuristics import analyze_address, detect_change

from .models import btc

from .profile import build_profile, trace_back

from .scoring import score

from .validate import normalize_address





def trace(

    seed,

    provider,

    labels,

    max_hops=3,

    start=None,

    end=None,

    max_states=30,

    max_txs=100,

):

    seed = normalize_address(seed)



    # Hard limits prevent unexpectedly expensive live investigations.

    max_states = max(1, min(int(max_states), 40))

    max_txs = max(1, min(int(max_txs), 100))

    max_hops = max(0, min(int(max_hops), 5))

    max_address_queries = 20



    history_cache = {}

    analysis_cache = {}

    excluded = set()

    truncated_addresses = set()

    skipped_addresses = set()



    def history(address):

        """Cache histories and enforce a global address-query budget."""

        if address in history_cache:

            return history_cache[address]



        if len(history_cache) >= max_address_queries:

            skipped_addresses.add(address)

            return []



        txs, cut = provider.address_txs(address, max_txs)

        history_cache[address] = txs



        if cut:

            truncated_addresses.add(address)



        return history_cache[address]



    def analysis(address):

        if address not in analysis_cache:

            analysis_cache[address] = analyze_address(

                address,

                history(address),

                labels,

            )

        return analysis_cache[address]



    def usable(tx):

        if not tx.get("confirmed", False):

            excluded.add(tx["txid"])

            return False



        tx_time = tx.get("time")



        if tx_time is None:

            excluded.add(tx["txid"])

            return False



        if start is not None and tx_time < start:

            excluded.add(tx["txid"])

            return False



        if end is not None and tx_time > end:

            excluded.add(tx["txid"])

            return False



        return True



    seed_txs = history(seed)



    received = [

        (tx, output)

        for tx in seed_txs

        if usable(tx)

        for output in tx.get("outputs", [])

        if output.get("address") == seed

    ]



    total_received = sum(

        output["value"] for _, output in received

    ) or 1



    candidates = []

    seen_candidates = set()

    unspent_ends = set()

    boundaries = set()

    discovered = {seed}

    used_steps = {}



    def add_candidate(

        match,

        label,

        via,

        address,

        hops,

        steps,

        flags,

        value,

    ):

        key = (address, tuple(step["id"] for step in steps))



        if key in seen_candidates:

            return



        seen_candidates.add(key)



        level, points, reasons = score(

            match,

            label,

            hops,

            flags["weak"],

            flags["unresolved"],

            address in truncated_addresses,

        )



        if via:

            reasons.append(f"Matched through related address {via}")



        candidates.append(

            {

                "vasp": label["entity"],

                "address": address,

                "hops": hops,

                "transactions": steps,

                "label": label,

                "match": match,

                "via": via,

                "confidence": level,

                "confidence_score": points,

                "reasons": reasons,

                "amount": btc(value),
                "amount_basis": "transaction_output_value",
                "share_upper_bound": None,
                "amount_note": (
                    "Full transaction output value shown; the seed-origin share "
                    "is unknown because inputs may combine funds from multiple sources."
                ),

            }

        )



    if seed in labels:

        add_candidate(

            "label",

            labels[seed],

            None,

            seed,

            0,

            [],

            {"weak": 0, "unresolved": 0},

            total_received,

        )



    # Payment paths receive priority. Change paths remain available but

    # cannot crowd out every payment path in the exploration queue.

    payment_queue = deque()

    change_queue = deque()



    if seed not in labels:

        for tx, output in received:

            payment_queue.append(

                (

                    tx["txid"],

                    output["n"],

                    seed,

                    0,

                    [],

                    {"weak": 0, "unresolved": 0},

                )

            )



    seen_outputs = set()

    expansions = 0



    while (

        payment_queue or change_queue

    ) and expansions < max_states:



        queue = payment_queue if payment_queue else change_queue



        txid, vout, address, hops, steps, flags = queue.popleft()

        output_key = (txid, vout)



        if output_key in seen_outputs:

            continue



        seen_outputs.add(output_key)

        expansions += 1



        address_history = history(address)



        if address in skipped_addresses:

            continue



        spender = next(

            (

                tx

                for tx in address_history

                if usable(tx)

                and any(

                    item["txid"] == txid

                    and item["vout"] == vout

                    for item in tx.get("inputs", [])

                )

            ),

            None,

        )



        if spender is None:

            # A skipped history is not evidence that an output is unspent.

            if address not in skipped_addresses:

                unspent_ends.add(address)

            continue



        inputs = spender.get("inputs", [])

        outputs = [

            output

            for output in spender.get("outputs", [])

            if output.get("address")

        ]



        input_addresses = {

            item["address"]

            for item in inputs

            if item.get("address")

        }



        change_index, strength = detect_change(

            spender,

            input_addresses,

        )



        other_outputs = [

            output

            for output in outputs

            if output["address"] not in input_addresses

        ]



        unresolved = (

            len(other_outputs) >= 2

            and change_index is None

        )



        payment_children = []

        change_children = []



        for output in outputs:

            output_address = output["address"]



            if output_address in input_addresses:

                kind = "change-reuse"

            elif output["n"] == change_index:

                kind = "change"

            else:

                kind = "payment"



            timestamp = spender.get("time")



            step = {

                "id": f"{spender['txid']}:{output['n']}",

                "txid": spender["txid"],

                "from": address,

                "to": output_address,

                "amount": btc(output["value"]),

                "asset": "BTC",

                "timestamp": (

                    timestamp.isoformat()

                    if timestamp is not None

                    else None

                ),

                "kind": kind,

                "direction": "out",

            }



            new_flags = {

                "weak": flags["weak"] + int(

                    kind == "change" and strength == "weak"

                ),

                "unresolved": flags["unresolved"] + int(

                    kind == "payment" and unresolved

                ),

            }



            new_steps = steps + [step]



            if kind != "payment":

                discovered.add(output_address)

                used_steps[step["id"]] = step



                change_children.append(

                    (

                        spender["txid"],

                        output["n"],

                        output_address,

                        hops,

                        new_steps,

                        new_flags,

                    )

                )

                continue



            if hops + 1 > max_hops:

                boundaries.add(address)

                continue



            discovered.add(output_address)

            used_steps[step["id"]] = step



            # Direct labels can be checked without querying the provider.

            if output_address in labels:

                add_candidate(

                    "label",

                    labels[output_address],

                    None,

                    output_address,

                    hops + 1,

                    new_steps,

                    new_flags,

                    output["value"],

                )

                continue



            found = analysis(output_address)



            if output_address in skipped_addresses:

                continue



            if found.get("cluster"):

                label, via = found["cluster"]



                add_candidate(

                    "cluster",

                    label,

                    via,

                    output_address,

                    hops + 1,

                    new_steps,

                    new_flags,

                    output["value"],

                )

                continue



            if found.get("deposit_like"):

                pattern = {

                    "entity": (

                        "Possible exchange deposit address (no label)"

                    ),

                    "type": "deposit-pattern",

                    "source": (

                        f"Heuristic: {found['senders']} different senders, "

                        "then single-output sweeps"

                    ),

                    "verified": False,

                }



                add_candidate(

                    "pattern",

                    pattern,

                    None,

                    output_address,

                    hops + 1,

                    new_steps,

                    new_flags,

                    output["value"],

                )



            payment_children.append(

                (

                    spender["txid"],

                    output["n"],

                    output_address,

                    hops + 1,

                    new_steps,

                    new_flags,

                )

            )



        # Insert newly found payment branches before change branches.

        payment_queue.extend(payment_children)

        change_queue.extend(change_children)



    names = getattr(provider, "names", {})



    back = {

        "boundary": False,

        "coinbase_inputs": 0,

        "steps": [],

        "sources": [],

        "budget_exhausted": False,

    }



    if seed_txs:

        try:

            back = trace_back(

                seed,

                history,

                usable,

                labels,

                names,

                max_hops,

                max_states,

            )

        except Exception:

            # Keep forward evidence if backward tracing fails.

            back = {

                "boundary": False,

                "coinbase_inputs": 0,

                "steps": [],

                "sources": [],

                "budget_exhausted": True,

            }



    for step in back.get("steps", []):

        for address_value in (step.get("from"), step.get("to")):

            if address_value:

                discovered.add(address_value)



    try:

        seed_analysis = analysis(seed)



        profile = build_profile(

            seed,

            seed_txs,

            labels,

            names,

            seed_analysis,

            seed in truncated_addresses,

        )

    except Exception:

        profile = {

            "address": seed,

            "name": names.get(seed, "Unknown wallet"),

            "label": labels.get(seed),

            "warning": "Wallet profile could not be fully generated.",

        }



    candidates.sort(

        key=lambda candidate: (

            candidate["hops"],

            -candidate["confidence_score"],

            candidate["address"],

        )

    )



    verified_labels = [
        candidate
        for candidate in candidates
        if candidate["match"] == "label"
        and candidate.get("label", {}).get("verified") is True
    ]
    non_pattern = [
        candidate
        for candidate in candidates
        if candidate["match"] != "pattern"
    ]
    nearest = (
        verified_labels[0]
        if verified_labels
        else non_pattern[0]
        if non_pattern
        else candidates[0]
        if candidates
        else None
    )



    pending_work = bool(payment_queue or change_queue)



    limited = (

        pending_work

        or bool(boundaries)

        or bool(truncated_addresses)

        or bool(skipped_addresses)

        or expansions >= max_states

        or back.get("budget_exhausted", False)

    )



    if not seed_txs:

        status = (

            "not_in_demo"

            if provider.name == "fixture"

            else "no_activity"

        )

    elif limited:

        status = "limited"

    else:

        status = "completed"



    limitations = [

        (

            "Attribution results are investigative leads, not proof. "

            "Labels and heuristics can be wrong; investigators must "

            "confirm each step."

        ),

        (

            "Mixers, CoinJoin, cross-chain bridges and swaps are not "

            "detected. Funds entering them may not be traceable here."

        ),

        (

            "Transactions with multiple inputs can blend funds. "

            "Share values are upper bounds, not proven ownership."

        ),

        (

            "Change-address detection is heuristic. Paths relying on "

            "weak change detection receive lower confidence."

        ),

    ]



    if provider.name == "fixture":

        limitations.insert(

            0,

            "Synthetic fixture data was used; no live blockchain "

            "or exchange intelligence was queried.",

        )



    if pending_work or expansions >= max_states:

        limitations.append(

            "The exploration budget (state limit) was reached. "

            "The result may be incomplete."

        )



    if boundaries:

        limitations.append(

            "The hop limit was reached. Additional endpoints may "

            "exist beyond the displayed paths."

        )



    if truncated_addresses:

        limitations.append(

            "Some address histories exceeded the transaction-fetch "

            "limit and were truncated."

        )



    if skipped_addresses:

        limitations.append(

            f"The address-query budget was reached. "

            f"{len(skipped_addresses)} address(es) could not be examined."

        )



    if unspent_ends:

        limitations.append(

            f"{len(unspent_ends)} followed output(s) appear unspent "

            "in the fetched history. The trail stops there until "

            "those outputs are spent."

        )



    if not seed_txs:

        limitations.append(

            "No transactions were found for this address in the data "

            "source. No tracing conclusion can be drawn."

        )



    if back.get("boundary"):

        limitations.append(

            "Source tracing stopped at the hop limit. "

            "Older funding sources may exist."

        )



    if back.get("coinbase_inputs"):

        limitations.append(

            "Some funds trace back to newly mined coins (coinbase)."

        )



    if back.get("budget_exhausted"):

        limitations.append(

            "Backward source tracing reached its exploration budget."

        )



    all_steps = list(used_steps.values()) + back.get("steps", [])



    unique_steps = {

        step["id"]: step

        for step in all_steps

        if step.get("id")

    }



    transactions = sorted(

        unique_steps.values(),

        key=lambda step: (

            step.get("timestamp") or "",

            step.get("id") or "",

        ),

    )



    return {

        "status": status,

        "seed": seed,
        "history_diagnostics": {
            "transaction_limit_per_address": max_txs,
            "truncated_addresses": sorted(truncated_addresses),
            "seed_history_truncated": seed in truncated_addresses,
        },

        "network": "Bitcoin",

        "asset": "BTC",

        "mode": provider.name,

        "max_hops": max_hops,

        "transactions": transactions,

        "profile": profile,

        "sources": back.get("sources", []),

        "nodes": [

            {

                "address": address,

                "name": names.get(address, "Unknown wallet"),

                "label": labels.get(address),

            }

            for address in sorted(discovered)

        ],

        "candidates": candidates,

        "nearest": nearest,

        "excluded_time_transfers": sorted(excluded),

        "limitations": limitations,

    }
