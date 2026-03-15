import pytest

from models.spotify_player import SpotifyCollection, SpotifyPlayer, SpotifyTrack


def test_is_spotify_url():
    player = SpotifyPlayer()

    assert player.is_spotify_url("https://open.spotify.com/album/abc123?si=test")
    assert player.is_spotify_url("https://open.spotify.com/playlist/abc123")
    assert player.is_spotify_url("https://open.spotify.com/track/abc123")
    assert player.is_spotify_url("https://open.spotify.com/intl-en/album/abc123")
    assert player.is_spotify_url("https://www.open.spotify.com/album/abc123")

    assert not player.is_spotify_url("https://example.com/album/abc123")
    assert not player.is_spotify_url("https://open.spotify.com/artist/abc123")


@pytest.mark.asyncio
async def test_resolve_album_from_ld_json(monkeypatch):
    player = SpotifyPlayer()

    album_html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "MusicAlbum",
      "name": "LD Album",
      "track": [
        {"@type": "MusicRecording", "name": "Song 1", "byArtist": {"name": "Artist 1"}},
        {"@type": "MusicRecording", "name": "Song 2", "byArtist": [{"name": "Artist 2"}, {"name": "Feat"}]}
      ]
    }
    </script>
    </head><body></body></html>
    """

    monkeypatch.setattr(player, "_fetch_html", lambda _url: album_html)

    collection = await player.resolve_collection("https://open.spotify.com/album/test_album")

    assert collection == SpotifyCollection(
        source_type="album",
        source_name="LD Album",
        tracks=(
            SpotifyTrack(title="Song 1", artists=("Artist 1",)),
            SpotifyTrack(title="Song 2", artists=("Artist 2", "Feat")),
        ),
    )


@pytest.mark.asyncio
async def test_resolve_playlist_uses_next_data_fallback(monkeypatch):
    player = SpotifyPlayer()

    playlist_html = """
    <html><head>
    <meta property="og:title" content="Fallback Playlist" />
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "state": {
            "name": "Fallback Playlist",
            "items": [
              {
                "track": {
                  "type": "track",
                  "uri": "spotify:track:one",
                  "name": "Track One",
                  "artists": [{"name": "Artist One"}]
                }
              },
              {
                "track": {
                  "type": "episode",
                  "uri": "spotify:episode:ignored",
                  "name": "Ignore Episode"
                }
              },
              {
                "track": {
                  "__typename": "Track",
                  "uri": "spotify:track:two",
                  "name": "Track Two",
                  "artists": [{"name": "Artist Two"}]
                }
              }
            ]
          }
        }
      }
    }
    </script>
    </head><body></body></html>
    """

    monkeypatch.setattr(player, "_fetch_html", lambda _url: playlist_html)

    collection = await player.resolve_collection("https://open.spotify.com/playlist/test_playlist")

    assert collection == SpotifyCollection(
        source_type="playlist",
        source_name="Fallback Playlist",
        tracks=(
            SpotifyTrack(title="Track One", artists=("Artist One",)),
            SpotifyTrack(title="Track Two", artists=("Artist Two",)),
        ),
    )


@pytest.mark.asyncio
async def test_resolve_track_from_ld_json(monkeypatch):
    player = SpotifyPlayer()

    track_html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "MusicRecording",
      "name": "Single Track",
      "byArtist": {"name": "Single Artist"}
    }
    </script>
    </head><body></body></html>
    """

    monkeypatch.setattr(player, "_fetch_html", lambda _url: track_html)

    collection = await player.resolve_collection("https://open.spotify.com/track/test_track")

    assert collection == SpotifyCollection(
        source_type="track",
        source_name="Single Track",
        tracks=(SpotifyTrack(title="Single Track", artists=("Single Artist",)),),
    )


@pytest.mark.asyncio
async def test_resolve_playlist_from_spotify_entity_nd_variant(monkeypatch):
    player = SpotifyPlayer()

    empty_html = "<html><head><title>No tracks</title></head><body></body></html>"
    entity_html = """
    <html><head>
    <script>
    Spotify.Entity = {
      "type": "playlist",
      "name": "Entity Playlist",
      "tracks": {
        "items": [
          {"track": {"type": "track", "name": "Entity Song 1", "artists": [{"name": "Entity Artist 1"}]}},
          {"track": {"type": "track", "name": "Entity Song 2", "artists": [{"name": "Entity Artist 2"}]}}
        ]
      }
    };
    </script>
    </head><body></body></html>
    """

    expected_base = "https://open.spotify.com/playlist/test_entity_playlist"
    expected_nd = f"{expected_base}?nd=1"
    requested_urls = []

    def fake_fetch(url):
        requested_urls.append(url)
        if url == expected_nd:
            return entity_html
        return empty_html

    async def fake_chosic(_spotify_url, _playlist_id):
        return None

    monkeypatch.setattr(player, "_resolve_playlist_via_chosic", fake_chosic)
    monkeypatch.setattr(player, "_fetch_html", fake_fetch)

    collection = await player.resolve_collection(expected_base)

    assert requested_urls[:2] == [expected_base, expected_nd]
    assert collection == SpotifyCollection(
        source_type="playlist",
        source_name="Entity Playlist",
        tracks=(
            SpotifyTrack(title="Entity Song 1", artists=("Entity Artist 1",)),
            SpotifyTrack(title="Entity Song 2", artists=("Entity Artist 2",)),
        ),
    )


@pytest.mark.asyncio
async def test_resolve_playlist_from_track_anchor_fallback(monkeypatch):
    player = SpotifyPlayer()

    anchor_html = """
    <html><head><meta property="og:title" content="Anchor Playlist" /></head>
    <body>
      <a href="/track/1111111111111111111111">Anchor Song One</a>
      <a href="/track/2222222222222222222222">Anchor Song Two</a>
    </body></html>
    """

    monkeypatch.setattr(player, "_fetch_html", lambda _url: anchor_html)

    collection = await player.resolve_collection("https://open.spotify.com/playlist/anchor_playlist")

    assert collection == SpotifyCollection(
        source_type="playlist",
        source_name="Anchor Playlist",
        tracks=(
            SpotifyTrack(title="Anchor Song One", artists=tuple()),
            SpotifyTrack(title="Anchor Song Two", artists=tuple()),
        ),
    )


def test_tracks_from_track_uri_name_heuristic_handles_escaped_json():
    player = SpotifyPlayer()
    html = (
        '... "uri":"spotify\\\\u003Atrack\\\\u003A7abcDEF12345" '
        '"name":"First\\\\u0020Track" ... '
        '... "uri":"spotify:track:9xyzXYZ67890" "name":"Second Track" ...'
    )

    tracks = player._tracks_from_track_uri_name_heuristic(html)

    assert tracks == [
        SpotifyTrack(title="First Track", artists=tuple()),
        SpotifyTrack(title="Second Track", artists=tuple()),
    ]


def test_extract_first_form_for_chosic_exporter():
    player = SpotifyPlayer()
    html = """
    <html><body>
      <form action="/spotify-playlist-exporter/" method="post">
        <input type="hidden" name="nonce" value="abc123" />
        <input type="url" name="playlist_url" value="" />
        <input type="submit" value="Export" />
      </form>
    </body></html>
    """

    form = player._extract_first_form(html)

    assert form is not None
    action_url, method, payload, target_field = form
    assert action_url == "https://www.chosic.com/spotify-playlist-exporter/"
    assert method == "post"
    assert target_field == "playlist_url"
    assert payload["nonce"] == "abc123"


def test_extract_export_download_links_prefers_txt_then_csv():
    player = SpotifyPlayer()
    html = """
    <html><body>
      <a href="/exports/my-list.csv">CSV</a>
      <a href="/exports/my-list.txt">TXT</a>
      <a href="/exports/my-list.csv">CSV duplicate</a>
    </body></html>
    """

    links = player._extract_export_download_links(html, "https://www.chosic.com/results")

    assert links == [
        "https://www.chosic.com/exports/my-list.txt",
        "https://www.chosic.com/exports/my-list.csv",
    ]


def test_parse_csv_export_tracks_and_artists():
    player = SpotifyPlayer()
    csv_text = """Track Name,Artist(s)
Song A,"Artist 1, Artist 2"
Song B,Artist 3
"""

    tracks = player._parse_csv_export(csv_text)

    assert tracks == [
        SpotifyTrack(title="Song A", artists=("Artist 1", "Artist 2")),
        SpotifyTrack(title="Song B", artists=("Artist 3",)),
    ]


def test_parse_txt_export_tracks():
    player = SpotifyPlayer()
    txt_text = """
Playlist: Example
1. Artist A - Song A
2) Song B
Tracks: 2
"""

    tracks = player._parse_txt_export(txt_text)

    assert tracks == [
        SpotifyTrack(title="Song A", artists=("Artist A",)),
        SpotifyTrack(title="Song B", artists=tuple()),
    ]


def test_parse_csv_export_artist_column_before_track_column():
    player = SpotifyPlayer()
    csv_text = """Artist Name,Track Name
Artist A,Song A
Artist B,Song B
"""

    tracks = player._parse_csv_export(csv_text)

    assert tracks == [
        SpotifyTrack(title="Song A", artists=("Artist A",)),
        SpotifyTrack(title="Song B", artists=("Artist B",)),
    ]


@pytest.mark.asyncio
async def test_resolve_playlist_via_chosic_happy_path(monkeypatch):
    player = SpotifyPlayer()
    playlist_url = "https://open.spotify.com/playlist/test_playlist"

    landing_html = """
    <html><body>
      <form action="/spotify-playlist-exporter/" method="post">
        <input type="hidden" name="nonce" value="abc123" />
        <input type="url" name="playlist_url" value="" />
      </form>
    </body></html>
    """
    result_html = """
    <html><head><meta property="og:title" content="My Playlist" /></head>
    <body><a href="/exports/test.csv">Download CSV</a></body></html>
    """

    monkeypatch.setattr(player, "_fetch_html", lambda _url: landing_html)

    def fake_submit(action_url, method, payload, referer):
        assert action_url == "https://www.chosic.com/spotify-playlist-exporter/"
        assert method == "post"
        assert payload["playlist_url"] == playlist_url
        assert referer == "https://www.chosic.com/spotify-playlist-exporter/"
        return "https://www.chosic.com/spotify-playlist-exporter/", result_html

    monkeypatch.setattr(player, "_submit_form_and_read_html", fake_submit)
    monkeypatch.setattr(
        player,
        "_download_and_parse_export",
        lambda _url: [
            SpotifyTrack(title="Song One", artists=("Artist One",)),
            SpotifyTrack(title="Song Two", artists=("Artist Two",)),
        ],
    )

    collection = await player._resolve_playlist_via_chosic(playlist_url, "test_playlist")

    assert collection == SpotifyCollection(
        source_type="playlist",
        source_name="My Playlist",
        tracks=(
            SpotifyTrack(title="Song One", artists=("Artist One",)),
            SpotifyTrack(title="Song Two", artists=("Artist Two",)),
        ),
    )
