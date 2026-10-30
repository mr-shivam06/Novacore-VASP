"""Where transactions come from. Both providers return the same normalized shape.

FixtureProvider reads a local JSON file (offline demo, tests).
EsploraProvider reads a public Esplora-style API (for example Blockstream or mempool.space).
"""

import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from .models import normalize_tx


class ProviderError(Exception):
    pass


class FixtureProvider:
    name = "fixture"

    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.examples = data.get("examples", [])
        self.names = data.get("names", {})
        self._index = defaultdict(dict)

        for raw in data["txs"]:
            tx = normalize_tx(raw)

            for item in tx["inputs"] + tx["outputs"]:
                if item["address"]:
                    self._index[item["address"]][tx["txid"]] = tx

    def knows(self, address):
        return address in self._index

    def address_txs(self, address, limit):
        txs = sorted(
            self._index.get(address, {}).values(),
            key=lambda t: (
                t["time"].timestamp() if t["time"] else 1e18,
                t["txid"],
            ),
        )

        return txs[:limit], len(txs) > limit


class EsploraProvider:
    name = "esplora"
    PAGE = 25  # Esplora returns 25 confirmed transactions per page

    def __init__(
        self,
        base_url="https://blockstream.info/api",
        fetch=None,
        pause=0.2,
    ):
        self.base_url = base_url.rstrip("/")
        self.names = {}
        self.examples = []
        self._fetch = fetch or self._http_get
        self._pause = pause

        # Cache address histories for the lifetime of this provider.
        self._history_cache = {}

    def knows(self, address):
        # Live Esplora can check addresses that are not in our local index.
        return True

    def _http_get(self, url):
        """Fetch JSON with a timeout and a limited number of retries."""
        last = None

        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "vasp-desk/0.3"},
                )

                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            except urllib.error.HTTPError as error:
                last = error

                # Retry only temporary server errors and rate limiting.
                if error.code not in (429, 500, 502, 503, 504):
                    break

            except (urllib.error.URLError, TimeoutError) as error:
                last = error

            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))

        raise ProviderError(f"Data provider request failed: {last}")

    def address_txs(self, address, limit):
        """Return normalized transactions and whether history was truncated."""
        cache_key = (address, limit)

        # Avoid repeating identical history requests during this server session.
        if cache_key in self._history_cache:
            txs, truncated = self._history_cache[cache_key]
            return txs, truncated

        raw = []
        seen = set()

        url = f"{self.base_url}/address/{address}/txs"

        while True:
            page = self._fetch(url)

            fresh = [
                tx for tx in page
                if tx["txid"] not in seen
            ]

            for tx in fresh:
                seen.add(tx["txid"])

            raw.extend(fresh)

            confirmed = [
                tx for tx in page
                if (tx.get("status") or {}).get("confirmed")
            ]

            # Esplora pages may include unconfirmed transactions. Use the
            # overall page length to decide whether another page may exist;
            # use the last confirmed transaction as the pagination cursor.
            page_may_have_more = len(page) >= self.PAGE and bool(confirmed)

            if (
                len(raw) >= limit
                or len(page) < self.PAGE
                or not confirmed
                or not fresh
            ):
                break

            url = (
                f"{self.base_url}/address/{address}/txs/chain/"
                f'{confirmed[-1]["txid"]}'
            )

            time.sleep(self._pause)

        truncated = (
            len(raw) > limit
            or (
                len(raw) >= limit
                and page_may_have_more
            )
        )

        txs = [
            normalize_tx(tx)
            for tx in raw[:limit]
        ]

        self._history_cache[cache_key] = (txs, truncated)

        return txs, truncated
    