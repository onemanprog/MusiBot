import asyncio
import csv
import json
import re
from dataclasses import dataclass
from html import unescape
from io import StringIO
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from loguru import logger
from playwright.async_api import async_playwright


SPOTIFY_WEB_BASE = "https://open.spotify.com"
SPOTIFY_RESOURCE_TYPES = {"album", "playlist", "track"}
CHOSIC_EXPORTER_URL = "https://www.chosic.com/spotify-playlist-exporter/"


@dataclass(frozen=True)
class SpotifyTrack:
    title: str
    artists: tuple[str, ...]

    @property
    def display_title(self) -> str:
        if not self.artists:
            return self.title
        return f"{self.title} - {', '.join(self.artists)}"

    @property
    def search_query(self) -> str:
        if not self.artists:
            return self.title
        return f"{self.title} {' '.join(self.artists)}"


@dataclass(frozen=True)
class SpotifyCollection:
    source_type: str
    source_name: str
    tracks: tuple[SpotifyTrack, ...]


class SpotifyPlayer:
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

    @classmethod
    def is_spotify_url(cls, value: str) -> bool:
        return cls._parse_spotify_resource(value) is not None

    async def resolve_collection(self, spotify_url: str) -> SpotifyCollection | None:
        parsed = self._parse_spotify_resource(spotify_url)
        if parsed is None:
            logger.debug(f"Not a supported Spotify URL: {spotify_url}")
            return None

        resource_type, resource_id = parsed
        if resource_type == "playlist":
            chosic_collection = await self._resolve_playlist_via_chosic(spotify_url, resource_id)
            if chosic_collection is not None and chosic_collection.tracks:
                return chosic_collection

        base_url = f"{SPOTIFY_WEB_BASE}/{resource_type}/{resource_id}"
        candidate_urls = self._candidate_urls(resource_type, resource_id)
        logger.debug(f"Resolving Spotify resource without auth: type={resource_type}, id={resource_id}")
        last_error = None
        for url in candidate_urls:
            try:
                html = await asyncio.to_thread(self._fetch_html, url)
            except Exception as exc:
                last_error = exc
                logger.warning(f"Failed to fetch Spotify page variant ({url}): {exc}")
                continue

            logger.debug(f"Spotify HTML markers for variant {url}: {self._html_marker_summary(html)}")
            source_name, tracks = self._extract_collection_from_html(html, resource_type, resource_id)
            if not tracks:
                logger.debug(f"Spotify page parsing returned no tracks for variant: {url}")
                continue

            logger.debug(
                "Resolved Spotify {} with {} track(s): {}",
                resource_type,
                len(tracks),
                source_name,
            )
            return SpotifyCollection(
                source_type=resource_type,
                source_name=source_name,
                tracks=tuple(tracks),
            )

        if last_error is not None:
            logger.error(f"Failed to resolve Spotify URL after all variants ({base_url}): {last_error}")
        else:
            logger.debug("Spotify page parsing returned no tracks")
        return None

    async def _resolve_playlist_via_chosic(
        self,
        spotify_playlist_url: str,
        playlist_id: str,
    ) -> SpotifyCollection | None:
        tracks: list[SpotifyTrack] = []
        source_name = f"playlist:{playlist_id}"
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=self._USER_AGENT)
                
                try:
                    logger.debug(f"Navigating to Chosic exporter: {CHOSIC_EXPORTER_URL}")
                    await page.goto(CHOSIC_EXPORTER_URL, wait_until="networkidle", timeout=300000)
                    
                    # Fill in the Spotify URL
                    logger.debug(f"Filling in Spotify URL: {spotify_playlist_url}")
                    await page.fill('input#search-word', spotify_playlist_url)
                    
                    # Click the Start button
                    logger.debug("Clicking 'Start' button")
                    await page.click('button#analyze')
                    
                    # Wait for the tracks table to appear (up to 5 minutes)
                    logger.debug("Waiting for tracks table to appear...")
                    await page.wait_for_selector('table#tracks-table', timeout=300000)
                    
                    # Extract tracks from the table using JavaScript
                    extract_js = """
                    () => {
                        const table = document.getElementById('tracks-table');
                        if (!table) return [];
                        
                        const tracks = [];
                        const rows = table.querySelectorAll('tbody tr');
                        if (!rows.length) return [];
                        
                        // Common UI button/action labels to filter out
                        const uiLabels = new Set(['delete', 'edit', 'add', 'remove', 'play', 'pause', 'download', 'share', 'more', 'options', 'action', 'track', 'song', '×', '✕', '✘', '...']);
                        
                        // Find column indices for song and artist
                        const headerRow = table.querySelector('thead tr');
                        let songColIdx = -1;
                        let artistColIdx = -1;
                        
                        if (headerRow) {
                            const headers = headerRow.querySelectorAll('th');
                            headers.forEach((th, idx) => {
                                const text = th.textContent.toLowerCase().trim();
                                // Match song/track columns
                                if ((text.includes('song') || text.includes('track') || text.includes('title') || text.includes('name')) 
                                    && !text.includes('artist') && !text.includes('id')) {
                                    if (songColIdx === -1) songColIdx = idx;  // Take first match
                                }
                                // Match artist columns
                                if (text.includes('artist') || text.includes('by')) {
                                    if (artistColIdx === -1) artistColIdx = idx;  // Take first match
                                }
                            });
                        }
                        
                        // Fallback: analyze first data row to detect columns by content
                        if (songColIdx === -1 || artistColIdx === -1) {
                            const firstRow = rows[0];
                            if (firstRow) {
                                const cells = firstRow.querySelectorAll('td');
                                for (let i = 0; i < cells.length; i++) {
                                    const cellText = cells[i].textContent.trim();
                                    const isId = /^[a-zA-Z0-9]{20,}$/.test(cellText);  // Spotify IDs are 22 alphanumeric chars
                                    const hasNumbers = /\\d{2,}/.test(cellText);
                                    
                                    if (songColIdx === -1 && !isId && !hasNumbers && cellText.length > 3) {
                                        songColIdx = i;
                                    } else if (artistColIdx === -1 && i !== songColIdx && !isId && !hasNumbers && cellText.length > 2) {
                                        artistColIdx = i;
                                    }
                                }
                            }
                        }
                        
                        // Default fallback (skip ID columns which are typically first)
                        if (songColIdx === -1) songColIdx = 1;  // Skip column 0 (likely ID)
                        if (artistColIdx === -1) artistColIdx = 2;
                        
                        // Helper to clean text of UI labels and extra whitespace
                        function cleanText(text) {
                            if (!text) return '';
                            
                            // Remove common UI button text patterns (case-insensitive)
                            let cleaned = text
                                .replace(/delete\\s+track[\\s\\n]*/gi, '')
                                .replace(/edit\\s+track[\\s\\n]*/gi, '')
                                .replace(/remove\\s+track[\\s\\n]*/gi, '');
                            
                            // Split by newlines/whitespace and filter
                            const parts = cleaned.split(/[\\n\\r]+/).map(p => p.trim()).filter(p => {
                                const lower = p.toLowerCase();
                                // Skip if it's a UI label or too short
                                return p.length > 1 && !uiLabels.has(lower) && !/^[❌✕×✘]+$/.test(p);
                            });
                            
                            // Join with space, collapse multiple spaces
                            return parts.join(' ').replace(/\\s+/g, ' ').trim();
                        }
                        
                        rows.forEach(row => {
                            const cells = row.querySelectorAll('td');
                            if (cells.length > songColIdx) {
                                let title = cleanText(cells[songColIdx]?.textContent || '');
                                let artist = '';
                                
                                // Skip if title looks like a Spotify ID
                                if (/^[a-zA-Z0-9]{20,}$/.test(title)) {
                                    // This is likely an ID, try next column
                                    if (cells.length > (songColIdx + 1)) {
                                        title = cleanText(cells[songColIdx + 1]?.textContent || '');
                                    }
                                }
                                
                                // Get artist if column exists
                                if (artistColIdx >= 0 && cells[artistColIdx]) {
                                    artist = cleanText(cells[artistColIdx].textContent);
                                    // Skip if artist also looks like ID
                                    if (/^[a-zA-Z0-9]{20,}$/.test(artist)) {
                                        artist = '';
                                    }
                                }
                                
                                // Only add if we have a valid title
                                if (title && title.length > 2 && !/^[a-zA-Z0-9]{20,}$/.test(title)) {
                                    tracks.push({
                                        title: title,
                                        artists: artist ? [artist] : []
                                    });
                                }
                            }
                        });
                        
                        return tracks;
                    }
                    """
                    
                    extracted_data = await page.evaluate(extract_js)
                    
                    # Convert extracted data to SpotifyTrack objects
                    for item in extracted_data:
                        track = SpotifyTrack(
                            title=item.get('title', ''),
                            artists=tuple(item.get('artists', []))
                        )
                        if track.title:
                            tracks.append(track)
                    
                    if tracks:
                        logger.debug(f"Chosic extracted {len(tracks)} tracks from table")
                    else:
                        logger.debug("Chosic table extraction returned no tracks")
                    
                finally:
                    await browser.close()
                    
        except Exception as exc:
            logger.warning(f"Chosic browser automation failed: {exc}")
            return None
        
        if not tracks:
            logger.debug("Chosic parsing returned no tracks")
            return None
        
        return SpotifyCollection(
            source_type="playlist",
            source_name=source_name,
            tracks=tuple(self._dedupe_tracks(tracks)),
        )

    def _submit_form_and_read_html(
        self,
        action_url: str,
        method: str,
        payload: dict[str, str],
        referer: str,
    ) -> tuple[str, str]:
        encoded = urlencode(payload).encode("utf-8")
        request = Request(
            action_url,
            data=encoded if method == "post" else None,
            method="POST" if method == "post" else "GET",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": referer,
                "User-Agent": self._USER_AGENT,
            },
        )

        final_url = action_url
        if method == "get":
            query = urlencode(payload)
            separator = "&" if "?" in action_url else "?"
            request = Request(
                f"{action_url}{separator}{query}",
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": referer,
                    "User-Agent": self._USER_AGENT,
                },
            )

        with urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            html = response.read().decode("utf-8", errors="ignore")
        return final_url, html

    def _extract_first_form(self, html: str) -> tuple[str, str, dict[str, str], str] | None:
        form_pattern = re.compile(r"<form\b([^>]*)>(.*?)</form>", flags=re.IGNORECASE | re.DOTALL)
        input_pattern = re.compile(r"<input\b([^>]*)>", flags=re.IGNORECASE)
        textarea_pattern = re.compile(r"<textarea\b([^>]*)>", flags=re.IGNORECASE)

        for form_attrs, form_inner in form_pattern.findall(html):
            marker_blob = f"{form_attrs}\n{form_inner}"
            if not re.search(r"spotify|playlist|export|csv|txt", marker_blob, flags=re.IGNORECASE):
                continue

            action = self._attr(form_attrs, "action") or CHOSIC_EXPORTER_URL
            method = (self._attr(form_attrs, "method") or "post").strip().lower()
            action_url = urljoin(CHOSIC_EXPORTER_URL, action)
            payload: dict[str, str] = {}
            target_field = ""

            for input_attrs in input_pattern.findall(form_inner):
                name = (self._attr(input_attrs, "name") or "").strip()
                if not name:
                    continue
                input_type = (self._attr(input_attrs, "type") or "text").strip().lower()
                value = self._attr(input_attrs, "value") or ""
                if input_type in {"hidden", "submit", "button"}:
                    payload[name] = value
                    continue
                if input_type in {"text", "url", "search"} and not target_field:
                    target_field = name
                    payload[name] = value

            if not target_field:
                for textarea_attrs in textarea_pattern.findall(form_inner):
                    name = (self._attr(textarea_attrs, "name") or "").strip()
                    if not name:
                        continue
                    target_field = name
                    payload[name] = ""
                    break

            return action_url, method, payload, target_field
        return None

    @staticmethod
    def _attr(attrs: str, name: str) -> str:
        pattern = re.compile(rf"{name}\s*=\s*['\"]([^'\"]+)['\"]", flags=re.IGNORECASE)
        match = pattern.search(attrs or "")
        return match.group(1) if match else ""

    def _extract_export_download_links(self, html: str, response_url: str) -> list[str]:
        links: list[str] = []
        href_pattern = re.compile(r"href=['\"]([^'\"]+)['\"]", flags=re.IGNORECASE)
        text_blob = html or ""

        for href in href_pattern.findall(text_blob):
            lower = href.lower()
            if not any(token in lower for token in ("csv", "txt", "download", "export")):
                continue
            links.append(urljoin(response_url, href))

        for absolute in re.findall(
            r"https?://[^\"'\s<>]+",
            text_blob,
            flags=re.IGNORECASE,
        ):
            lower = absolute.lower()
            if any(token in lower for token in ("csv", "txt", "download", "export")):
                links.append(absolute)

        prioritized = sorted(
            self._dedupe_strings(links),
            key=lambda url: ("txt" not in url.lower(), "csv" not in url.lower()),
        )
        return prioritized

    def _download_and_parse_export(self, url: str) -> list[SpotifyTrack]:
        print("Downloading and parsing export from URL:", url)
        request = Request(
            url,
            headers={
                "Accept": "text/plain,text/csv,*/*;q=0.8",
                "Referer": CHOSIC_EXPORTER_URL,
                "User-Agent": self._USER_AGENT,
            },
        )
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            content_type = (response.headers.get("Content-Type") or "").lower()

        if "csv" in url.lower() or "csv" in content_type:
            tracks = self._parse_csv_export(raw)
            if tracks:
                return tracks

        # Many exporters serve CSV with generic content-type or TXT with no extension.
        txt_tracks = self._parse_txt_export(raw)
        if txt_tracks:
            return txt_tracks

        csv_tracks = self._parse_csv_export(raw)
        return csv_tracks

    def _parse_csv_export(self, text: str) -> list[SpotifyTrack]:
        print("Parsing CSV export...")
        rows = list(csv.reader(StringIO(text)))
        if not rows:
            return []

        header = [cell.strip().lower() for cell in rows[0]]
        title_idx = self._find_title_header_index(header)
        artist_idx = self._find_artist_header_index(header)
        start_row = 1 if title_idx is not None else 0
        if title_idx is None:
            non_artist_columns = [
                index for index, column in enumerate(header) if "artist" not in column
            ]
            title_idx = non_artist_columns[0] if non_artist_columns else 0

        tracks: list[SpotifyTrack] = []
        for row in rows[start_row:]:
            if title_idx >= len(row):
                continue
            title = row[title_idx].strip()
            if not title:
                continue
            artists: tuple[str, ...] = tuple()
            if artist_idx is not None and artist_idx < len(row):
                artists = self._split_artists(row[artist_idx])
            tracks.append(SpotifyTrack(title=title, artists=artists))
        return tracks

    def _parse_txt_export(self, text: str) -> list[SpotifyTrack]:
        print("Parsing text export...")
        tracks: list[SpotifyTrack] = []
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^\d+\s*[\).\-\:]\s*", "", line)
            if not line:
                continue
            lower = line.casefold()
            if lower.startswith(("playlist:", "tracks:", "total tracks", "exported")):
                continue

            title = line
            artists: tuple[str, ...] = tuple()
            if " - " in line:
                artist_part, title_part = line.split(" - ", 1)
                if artist_part.strip() and title_part.strip():
                    title = title_part.strip()
                    artists = self._split_artists(artist_part)

            tracks.append(SpotifyTrack(title=title, artists=artists))
        return tracks

    def _extract_tracks_from_simple_table(self, html: str) -> list[SpotifyTrack]:
        print("Extracting tracks from simple table...")
        # Last-resort parser if Chosic renders results directly in HTML table rows.
        row_pattern = re.compile(r"<tr\b[^>]*>(.*?)</tr>", flags=re.IGNORECASE | re.DOTALL)
        cell_pattern = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", flags=re.IGNORECASE | re.DOTALL)
        tag_pattern = re.compile(r"<[^>]+>")
        tracks: list[SpotifyTrack] = []

        for row in row_pattern.findall(html):
            cells = cell_pattern.findall(row)
            if not cells:
                continue
            first = unescape(tag_pattern.sub("", cells[0])).strip()
            if not first:
                continue
            if first.casefold() in {"track", "song", "title", "#"}:
                continue
            if first.isdigit() and len(cells) > 1:
                first = unescape(tag_pattern.sub("", cells[1])).strip()
            if not first:
                continue
            tracks.append(SpotifyTrack(title=first, artists=tuple()))
        return tracks

    @staticmethod
    def _find_header_index(header: list[str], candidates: set[str]) -> int | None:
        for idx, column in enumerate(header):
            if any(token in column for token in candidates):
                return idx
        return None

    @staticmethod
    def _find_title_header_index(header: list[str]) -> int | None:
        priority_tokens = [
            ("track name", "song name", "track title", "song title"),
            ("track", "song", "title"),
            ("name",),
        ]
        for token_group in priority_tokens:
            for idx, column in enumerate(header):
                if "artist" in column:
                    continue
                if any(token in column for token in token_group):
                    return idx
        return None

    @staticmethod
    def _find_artist_header_index(header: list[str]) -> int | None:
        for idx, column in enumerate(header):
            if "artist" in column:
                return idx
        return None

    @staticmethod
    def _split_artists(value: str) -> tuple[str, ...]:
        text = (value or "").strip()
        if not text:
            return tuple()
        parts = re.split(r"[;,/]|\s+&\s+|\s+feat\.\s+", text, flags=re.IGNORECASE)
        artists = tuple(part.strip() for part in parts if part.strip())
        return artists

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen = set()
        for value in values:
            key = value.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    def _extract_collection_from_html(
        self,
        html: str,
        resource_type: str,
        resource_id: str,
    ) -> tuple[str, list[SpotifyTrack]]:
        tracks = self._tracks_from_ld_json(html, resource_type)
        source_name = self._source_name_from_ld_json(html, resource_type)
        if tracks:
            logger.debug(f"Spotify parser hit: ld+json ({len(tracks)} tracks)")

        if not tracks:
            next_data = self._extract_next_data(html)
            if next_data is not None:
                tracks = self._tracks_from_next_data(next_data)
                if not source_name:
                    source_name = self._source_name_from_next_data(next_data, resource_type)
                if tracks:
                    logger.debug(f"Spotify parser hit: __NEXT_DATA__ ({len(tracks)} tracks)")

        if not tracks:
            entity_payload = self._extract_spotify_entity_payload(html)
            if entity_payload is not None:
                tracks = self._tracks_from_entity_payload(entity_payload)
                if not source_name:
                    source_name = self._source_name_from_entity_payload(entity_payload, resource_type)
                if tracks:
                    logger.debug(f"Spotify parser hit: Spotify.Entity ({len(tracks)} tracks)")

        if not tracks:
            tracks = self._tracks_from_script_json_blobs(html)
            if tracks:
                logger.debug(f"Spotify parser hit: generic script JSON ({len(tracks)} tracks)")

        if not tracks:
            tracks = self._tracks_from_track_anchor_links(html)
            if tracks:
                logger.debug(f"Spotify parser hit: HTML track anchors ({len(tracks)} tracks)")

        if not tracks:
            tracks = self._tracks_from_track_uri_name_heuristic(html)
            if tracks:
                logger.debug(f"Spotify parser hit: URI/name heuristic ({len(tracks)} tracks)")

        if not source_name:
            source_name = self._extract_og_title(html) or f"{resource_type}:{resource_id}"

        if resource_type == "track" and not tracks:
            inferred_track = self._infer_track_from_og_title(source_name)
            if inferred_track is not None:
                tracks = [inferred_track]

        return source_name, self._dedupe_tracks(tracks)

    def _tracks_from_ld_json(self, html: str, resource_type: str) -> list[SpotifyTrack]:
        tracks: list[SpotifyTrack] = []
        for obj in self._iter_ld_json_objects(html):
            obj_type = self._normalize_type(obj.get("@type"))

            if resource_type == "album" and obj_type == "musicalbum":
                tracks.extend(self._tracks_from_ld_track_field(obj.get("track")))
            elif resource_type == "playlist" and obj_type == "musicplaylist":
                tracks.extend(self._tracks_from_ld_track_field(obj.get("track")))
            elif resource_type == "track" and obj_type == "musicrecording":
                track = self._track_from_ld_item(obj)
                if track is not None:
                    tracks.append(track)

        return tracks

    def _source_name_from_ld_json(self, html: str, resource_type: str) -> str:
        type_map = {
            "album": "musicalbum",
            "playlist": "musicplaylist",
            "track": "musicrecording",
        }
        target_type = type_map.get(resource_type)
        if target_type is None:
            return ""

        for obj in self._iter_ld_json_objects(html):
            if self._normalize_type(obj.get("@type")) != target_type:
                continue
            name = obj.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return ""

    def _tracks_from_ld_track_field(self, track_field) -> list[SpotifyTrack]:
        if track_field is None:
            return []

        track_items = track_field if isinstance(track_field, list) else [track_field]
        tracks: list[SpotifyTrack] = []
        for item in track_items:
            if not isinstance(item, dict):
                continue

            candidate = item.get("item")
            if isinstance(candidate, dict):
                track = self._track_from_ld_item(candidate)
            else:
                track = self._track_from_ld_item(item)

            if track is not None:
                tracks.append(track)
        return tracks

    def _tracks_from_next_data(self, next_data: dict) -> list[SpotifyTrack]:
        tracks: list[SpotifyTrack] = []

        def _walk(value):
            if isinstance(value, dict):
                # Playlist JSON often nests real track payload under `track`.
                inner_track = value.get("track")
                if isinstance(inner_track, dict):
                    track = self._track_from_generic_item(inner_track) or self._track_from_soft_item(inner_track)
                    if track is not None:
                        tracks.append(track)

                track = self._track_from_generic_item(value) or self._track_from_soft_item(value)
                if track is not None:
                    tracks.append(track)

                for nested in value.values():
                    _walk(nested)
                return

            if isinstance(value, list):
                for nested in value:
                    _walk(nested)

        _walk(next_data)
        return tracks

    def _tracks_from_script_json_blobs(self, html: str) -> list[SpotifyTrack]:
        pattern = re.compile(r"<script[^>]*>(.*?)</script>", flags=re.IGNORECASE | re.DOTALL)
        tracks: list[SpotifyTrack] = []
        for raw_payload in pattern.findall(html):
            parsed = self._parse_embedded_json_blob(raw_payload)
            if parsed is None:
                continue
            tracks.extend(self._tracks_from_arbitrary_json(parsed))
        return tracks

    def _tracks_from_arbitrary_json(self, payload) -> list[SpotifyTrack]:
        tracks: list[SpotifyTrack] = []

        def _walk(value):
            if isinstance(value, dict):
                track = self._track_from_generic_item(value) or self._track_from_soft_item(value)
                if track is not None:
                    tracks.append(track)
                for nested in value.values():
                    _walk(nested)
                return

            if isinstance(value, list):
                for nested in value:
                    _walk(nested)

        _walk(payload)
        return tracks

    @staticmethod
    def _parse_embedded_json_blob(raw_payload: str):
        payload = unescape((raw_payload or "").strip())
        if not payload:
            return None

        parsed = SpotifyPlayer._try_parse_json(payload)
        if parsed is not None:
            return parsed

        # Common assignment forms: `window.foo = {...};`, `var x = [...];`
        assignment_patterns = [
            r"=\s*(\{.*\})\s*;?\s*$",
            r"=\s*(\[.*\])\s*;?\s*$",
        ]
        for pattern in assignment_patterns:
            match = re.search(pattern, payload, flags=re.DOTALL)
            if not match:
                continue
            parsed = SpotifyPlayer._try_parse_json(match.group(1))
            if parsed is not None:
                return parsed

        # Fallback: parse biggest JSON object/array fragment.
        for start_token, end_token in (("{", "}"), ("[", "]")):
            start = payload.find(start_token)
            end = payload.rfind(end_token)
            if start == -1 or end <= start:
                continue
            candidate = payload[start : end + 1]
            parsed = SpotifyPlayer._try_parse_json(candidate)
            if parsed is not None:
                return parsed

        return None

    @staticmethod
    def _try_parse_json(text: str):
        try:
            parsed = json.loads(text)
        except Exception:
            return None

        # Sometimes scripts contain a JSON-escaped string of JSON.
        if isinstance(parsed, str):
            try:
                second = json.loads(parsed)
                return second
            except Exception:
                return None
        return parsed

    def _tracks_from_entity_payload(self, payload: dict) -> list[SpotifyTrack]:
        tracks_root = payload.get("tracks")
        if isinstance(tracks_root, dict):
            items = tracks_root.get("items") or []
        elif isinstance(tracks_root, list):
            items = tracks_root
        else:
            items = []

        tracks: list[SpotifyTrack] = []
        for item in items:
            if isinstance(item, dict):
                track = self._track_from_entity_item(item)
                if track is not None:
                    tracks.append(track)
        return tracks

    def _source_name_from_entity_payload(self, payload: dict, resource_type: str) -> str:
        current_type = (payload.get("type") or "").strip().lower()
        if current_type and current_type != resource_type:
            return ""
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return ""

    def _source_name_from_next_data(self, next_data: dict, resource_type: str) -> str:
        target_type = resource_type

        def _walk(value):
            if isinstance(value, dict):
                current_type = (value.get("type") or value.get("__typename") or "").strip().lower()
                if current_type == target_type:
                    name = value.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
                for nested in value.values():
                    found = _walk(nested)
                    if found:
                        return found
                return ""

            if isinstance(value, list):
                for nested in value:
                    found = _walk(nested)
                    if found:
                        return found
            return ""

        return _walk(next_data)

    def _track_from_ld_item(self, item: dict) -> SpotifyTrack | None:
        title = (item.get("name") or "").strip()
        if not title:
            return None

        artists = self._extract_artist_names(item.get("byArtist"))
        return SpotifyTrack(title=title, artists=artists)

    def _track_from_generic_item(self, item: dict) -> SpotifyTrack | None:
        title = (item.get("name") or "").strip()
        if not title:
            return None

        track_type = (item.get("type") or item.get("__typename") or "").strip().lower()
        uri = (item.get("uri") or "").strip().lower()
        has_track_marker = (
            track_type == "track"
            or track_type == "musicrecording"
            or uri.startswith("spotify:track:")
        )
        if not has_track_marker:
            return None

        artists = self._extract_artist_names(
            item.get("artists")
            or item.get("artist")
            or item.get("byArtist")
            or item.get("artistsV2")
        )
        return SpotifyTrack(title=title, artists=artists)

    def _track_from_soft_item(self, item: dict) -> SpotifyTrack | None:
        title = (item.get("name") or item.get("title") or "").strip()
        if not title:
            return None

        if "tracks" in item and "track" not in item:
            return None

        artists_blob = (
            item.get("artists")
            or item.get("artist")
            or item.get("byArtist")
            or item.get("artistsV2")
        )
        artists = self._extract_artist_names(artists_blob)
        if not artists:
            return None

        return SpotifyTrack(title=title, artists=artists)

    def _track_from_entity_item(self, item: dict) -> SpotifyTrack | None:
        candidate = item.get("track")
        if isinstance(candidate, dict):
            item = candidate

        title = (item.get("name") or "").strip()
        if not title:
            return None

        track_type = (item.get("type") or item.get("__typename") or "").strip().lower()
        uri = (item.get("uri") or "").strip().lower()
        if track_type and track_type not in {"track", "musicrecording"} and not uri.startswith("spotify:track:"):
            return None

        artists = self._extract_artist_names(
            item.get("artists")
            or item.get("artist")
            or item.get("byArtist")
            or item.get("artistsV2")
        )
        return SpotifyTrack(title=title, artists=artists)

    def _tracks_from_track_anchor_links(self, html: str) -> list[SpotifyTrack]:
        # Fallback for server-rendered pages with direct track anchors.
        pattern = re.compile(
            r"<a[^>]+href=[\"']/track/[A-Za-z0-9]+[^\"']*[\"'][^>]*>(.*?)</a>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        tracks: list[SpotifyTrack] = []
        for raw_label in pattern.findall(html):
            label = re.sub(r"<[^>]+>", "", raw_label)
            label = unescape(label).strip()
            if not label:
                continue
            tracks.append(SpotifyTrack(title=label, artists=tuple()))
        return tracks

    def _tracks_from_track_uri_name_heuristic(self, html: str) -> list[SpotifyTrack]:
        tracks: list[SpotifyTrack] = []
        for blob in self._heuristic_blobs(html):
            tracks.extend(self._tracks_from_blob_uri_name_heuristic(blob))
        return self._dedupe_tracks(tracks)

    def _tracks_from_blob_uri_name_heuristic(self, blob: str) -> list[SpotifyTrack]:
        tracks: list[SpotifyTrack] = []
        if not blob:
            return tracks

        uri_patterns = [
            re.compile(r"spotify:track:([A-Za-z0-9]{10,40})"),
            re.compile(r"spotify\\u003Atrack\\u003A([A-Za-z0-9]{10,40})"),
            re.compile(r"spotify\\\\u003Atrack\\\\u003A([A-Za-z0-9]{10,40})"),
        ]
        name_patterns = [
            re.compile(r'"name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'),
            re.compile(r'\\"name\\"\s*:\s*\\"((?:[^\\"]|\\.)*)\\"'),
            re.compile(r'"title"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'),
            re.compile(r'\\"title\\"\s*:\s*\\"((?:[^\\"]|\\.)*)\\"'),
        ]

        uri_matches: list[tuple[int, int, str]] = []
        for uri_pattern in uri_patterns:
            for uri_match in uri_pattern.finditer(blob):
                uri_matches.append((uri_match.start(), uri_match.end(), uri_match.group(1)))

        seen_track_ids = set()
        for uri_start, uri_end, track_id in sorted(uri_matches, key=lambda item: item[0]):
            if not track_id or track_id in seen_track_ids:
                continue
            seen_track_ids.add(track_id)

            start = max(0, uri_start - 5000)
            end = min(len(blob), uri_end + 2500)
            window = blob[start:end]
            local_uri_pos = uri_start - start

            candidate_names: list[tuple[int, str]] = []
            for name_pattern in name_patterns:
                for name_match in name_pattern.finditer(window):
                    candidate_names.append((name_match.start(), name_match.group(1)))

            if not candidate_names:
                continue

            names_after_uri = sorted(
                (candidate for candidate in candidate_names if candidate[0] >= local_uri_pos),
                key=lambda item: item[0],
            )
            names_before_uri = sorted(
                (candidate for candidate in candidate_names if candidate[0] < local_uri_pos),
                key=lambda item: abs(local_uri_pos - item[0]),
            )

            for _, raw_name in [*names_after_uri, *names_before_uri]:
                decoded = self._decode_json_like_string(raw_name)
                if not decoded:
                    continue
                if len(decoded) > 180:
                    continue
                if decoded.casefold() in {"spotify", "track", "episode"}:
                    continue
                tracks.append(SpotifyTrack(title=decoded, artists=tuple()))
                break

        return tracks

    @staticmethod
    def _decode_json_like_string(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""

        candidate = text
        for _ in range(2):
            if not candidate:
                return ""
            try:
                decoded = json.loads(f"\"{candidate}\"")
                if isinstance(decoded, str):
                    candidate = decoded
                    continue
            except Exception:
                pass
            break

        decoded = (
            candidate.replace("\\u003A", ":")
            .replace("\\u002F", "/")
            .replace("\\/", "/")
            .replace("\\\"", "\"")
        )
        return unescape(decoded).strip()

    @staticmethod
    def _heuristic_blobs(html: str) -> list[str]:
        base = html or ""
        return [
            base,
            unescape(base),
            base.replace("\\u003A", ":").replace("\\u002F", "/").replace("\\/", "/"),
            unescape(base).replace("\\u003A", ":").replace("\\u002F", "/").replace("\\/", "/"),
        ]

    @staticmethod
    def _html_marker_summary(html: str) -> str:
        blob = html or ""
        escaped_track_marker = "spotify\\u003Atrack\\u003A"
        return (
            f"len={len(blob)} "
            f"ld_json={int('application/ld+json' in blob)} "
            f"next_data={int('__NEXT_DATA__' in blob)} "
            f"spotify_entity={int('Spotify.Entity' in blob)} "
            f"spotify_track_uri={int('spotify:track:' in blob)} "
            f"escaped_track_uri={int(escaped_track_marker in blob)} "
            f"track_anchor={int('/track/' in blob)}"
        )

    @staticmethod
    def _extract_artist_names(value) -> tuple[str, ...]:
        names: list[str] = []

        def _walk(node):
            if isinstance(node, str):
                text = node.strip()
                if text:
                    names.append(text)
                return

            if isinstance(node, dict):
                for key in ("name", "title"):
                    candidate = node.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        names.append(candidate.strip())
                for nested in node.values():
                    _walk(nested)
                return

            if isinstance(node, list):
                for nested in node:
                    _walk(nested)

        _walk(value)

        deduped: list[str] = []
        seen = set()
        for name in names:
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(name)
        return tuple(deduped)

    @classmethod
    def _iter_ld_json_objects(cls, html: str) -> list[dict]:
        pattern = re.compile(
            r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        objects: list[dict] = []
        for raw_payload in pattern.findall(html):
            payload = unescape(raw_payload).strip()
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            objects.extend(cls._flatten_ld_json(parsed))
        return objects

    @classmethod
    def _flatten_ld_json(cls, value) -> list[dict]:
        if isinstance(value, dict):
            items = [value]
            graph = value.get("@graph")
            if isinstance(graph, list):
                for nested in graph:
                    items.extend(cls._flatten_ld_json(nested))
            return items

        if isinstance(value, list):
            items: list[dict] = []
            for nested in value:
                items.extend(cls._flatten_ld_json(nested))
            return items

        return []

    @staticmethod
    def _extract_next_data(html: str) -> dict | None:
        pattern = re.compile(
            r"<script[^>]*id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html)
        if not match:
            return None

        payload = unescape(match.group(1)).strip()
        if not payload:
            return None

        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
        return None

    @staticmethod
    def _extract_spotify_entity_payload(html: str) -> dict | None:
        pattern = re.compile(
            r"Spotify\.Entity\s*=\s*(\{.*?\})\s*;",
            flags=re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html)
        if not match:
            return None

        payload = match.group(1).strip()
        if not payload:
            return None

        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
        return None

    @staticmethod
    def _extract_og_title(html: str) -> str:
        pattern = re.compile(
            r"<meta[^>]*property=[\"']og:title[\"'][^>]*content=[\"'](.*?)[\"'][^>]*>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html)
        if not match:
            return ""
        return unescape(match.group(1)).strip()

    @staticmethod
    def _infer_track_from_og_title(source_name: str) -> SpotifyTrack | None:
        title = (source_name or "").strip()
        if not title:
            return None
        return SpotifyTrack(title=title, artists=tuple())

    @staticmethod
    def _normalize_type(value) -> str:
        if isinstance(value, str):
            return value.strip().lower()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip().lower()
        return ""

    @classmethod
    def _fetch_html(cls, url: str) -> str:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.8",
                "User-Agent": cls._USER_AGENT,
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="ignore")

    @staticmethod
    def _dedupe_tracks(tracks: list[SpotifyTrack]) -> list[SpotifyTrack]:
        unique: list[SpotifyTrack] = []
        seen = set()
        for track in tracks:
            key = (
                track.title.casefold(),
                tuple(artist.casefold() for artist in track.artists),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(track)
        return unique

    @staticmethod
    def _candidate_urls(resource_type: str, resource_id: str) -> list[str]:
        base = f"{SPOTIFY_WEB_BASE}/{resource_type}/{resource_id}"
        embed = f"{SPOTIFY_WEB_BASE}/embed/{resource_type}/{resource_id}"
        return [
            base,
            f"{base}?nd=1",
            f"{base}?nd=1&app=desktop",
            embed,
            f"{embed}?utm_source=generator",
        ]

    @staticmethod
    def _parse_spotify_resource(value: str) -> tuple[str, str] | None:
        parsed = urlparse((value or "").strip())
        host = (parsed.netloc or "").lower().split(":", maxsplit=1)[0].rstrip(".")
        if host not in {"open.spotify.com", "www.open.spotify.com", "play.spotify.com"}:
            return None

        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return None

        if parts[0].startswith("intl-"):
            parts = parts[1:]

        if len(parts) < 2:
            return None

        resource_type = parts[0]
        if resource_type not in SPOTIFY_RESOURCE_TYPES:
            return None

        resource_id = parts[1].strip()
        if not resource_id:
            return None

        return resource_type, resource_id
