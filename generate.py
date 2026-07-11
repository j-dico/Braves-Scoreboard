"""
Braves Score Page Generator
----------------------------
Run this script to fetch live MLB data and regenerate index.html.
Then commit and push to GitHub to update your GitHub Pages site.

Usage:
    python3 generate.py
"""

import mlbstatsapi
from datetime import date, timedelta, datetime

NL_EAST_TEAMS = [144, 143, 146, 120, 121]  # ATL PHI MIA WSH NYM
BRAVES_ID     = 144
NL_EAST_DIVISION_ID = 204
NL_LEAGUE_ID  = 104
SEASON        = 2026

mlb = mlbstatsapi.Mlb()

def _build_team_map():
    teams = mlb.get_teams(sport_id=1)
    return {t.id: (getattr(t, "abbreviation", "???"), t.name) for t in teams}

TEAM_MAP = _build_team_map()


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def get_standings():
    records = []
    for division_record in mlb.get_standings(league_id=NL_LEAGUE_ID, season=SEASON):
        if division_record.division.id != NL_EAST_DIVISION_ID:
            continue
        for tr in division_record.team_records:
            abbr, full_name = TEAM_MAP.get(tr.team.id, ("???", tr.team.name))
            records.append({
                "team_id":  tr.team.id,
                "rank":     tr.division_rank,
                "team":     full_name,
                "abbr":     abbr,
                "is_braves": tr.team.id == BRAVES_ID,
                "w":        tr.wins,
                "l":        tr.losses,
                "pct":      tr.winning_percentage,
                "gb":       tr.games_back,
                "streak":   tr.streak.streak_code if tr.streak else "-",
                "l10":      next((r.wins   for r in tr.records.split_records if r.type == "lastTen"), "-"),
                "l10_l":    next((r.losses for r in tr.records.split_records if r.type == "lastTen"), "-"),
            })
    records.sort(key=lambda x: int(x["rank"]))
    return records


def get_recent_games(num_games=6):
    today = date.today()
    start = (today - timedelta(days=14)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    schedule = mlb.get_schedule(start_date=start, end_date=end, team_id=BRAVES_ID)
    games = []
    for sched_date in schedule.dates:
        for g in sched_date.games:
            status = g.status.abstract_game_state
            if status not in ("Final", "Live"):
                continue
            away, home = g.teams.away, g.teams.home
            braves_away  = away.team.id == BRAVES_ID
            opponent     = home.team.name if braves_away else away.team.name
            braves_score = away.score if braves_away else home.score
            opp_score    = home.score if braves_away else away.score
            at_symbol    = "@" if braves_away else "vs"
            won = None if status == "Live" else (
                braves_score is not None and opp_score is not None and braves_score > opp_score
            )
            games.append({
                "date":          sched_date.date,
                "opponent":      opponent,
                "at":            at_symbol,
                "braves_score":  braves_score,
                "opp_score":     opp_score,
                "status":        status,
                "won":           won,
                "detailed_state": g.status.detailed_state,
            })
    games.sort(key=lambda x: x["date"], reverse=True)
    return games[:num_games]


def get_todays_game(team_id):
    """Fetch today's game for any team. Returns a normalized game dict."""
    today    = date.today().strftime("%Y-%m-%d")
    schedule = mlb.get_schedule(date=today, team_id=team_id)
    if not schedule or not schedule.dates:
        return None
    for sched_date in schedule.dates:
        for g in sched_date.games:
            away, home   = g.teams.away, g.teams.home
            team_is_away = away.team.id == team_id
            team_abbr, _ = TEAM_MAP.get(team_id, ("???", ""))
            opp_id       = home.team.id if team_is_away else away.team.id
            opp_abbr, _  = TEAM_MAP.get(opp_id, ("???", ""))
            team_score   = (away.score if team_is_away else home.score) or 0
            opp_score    = (home.score if team_is_away else away.score) or 0
            status       = g.status
            venue        = g.venue.name if g.venue else ""

            # Linescore: inning, count, situation
            inning_info = ""
            balls = strikes = outs = None
            batter_name = pitcher_name = None
            on_first = on_second = on_third = False
            try:
                ls = mlb.get_game_line_score(g.game_pk)
                if ls and hasattr(ls, "current_inning"):
                    inn  = ls.current_inning or ""
                    half = ls.inning_half   or ""
                    if inn and half:
                        inning_info = f"{half} {inn}"
                    balls   = ls.balls
                    strikes = ls.strikes
                    outs    = ls.outs
                    if ls.offense:
                        if ls.offense.batter:
                            batter_name = ls.offense.batter.full_name
                        on_first  = ls.offense.first  is not None
                        on_second = ls.offense.second is not None
                        on_third  = ls.offense.third  is not None
                    if ls.defense and ls.defense.pitcher:
                        pitcher_name = ls.defense.pitcher.full_name
            except Exception:
                pass

            return {
                "team_id":        team_id,
                "team_abbr":      team_abbr,
                "opp_abbr":       opp_abbr,
                "team_is_away":   team_is_away,
                "team_score":     team_score,
                "opp_score":      opp_score,
                "abstract_state": status.abstract_game_state,
                "detailed_state": status.detailed_state,
                "reason":         status.reason or "",
                "venue":          venue,
                "inning_info":    inning_info,
                "balls":          balls,
                "strikes":        strikes,
                "outs":           outs,
                "batter_name":    batter_name,
                "pitcher_name":   pitcher_name,
                "on_first":       on_first,
                "on_second":      on_second,
                "on_third":       on_third,
            }
    return None


def get_roster_stats():
    """Fetch season stats for all active Braves players. Returns (hitters, pitchers)."""
    roster = mlb.get_team_roster(BRAVES_ID, roster_type='activeRoster')
    hitters, pitchers = [], []

    for player in roster:
        pid      = player.id
        name     = player.full_name
        pos_type = getattr(player.primary_position, 'type', '')        if player.primary_position else ''
        pos_abbr = getattr(player.primary_position, 'abbreviation', '') if player.primary_position else ''

        if pos_type == 'Pitcher':
            try:
                s = mlb.get_player_stats(pid, stats=['season'], groups=['pitching'])
                st = s['pitching']['season'].splits[0].stat
                ip  = float(st.innings_pitched or 0)
                k9  = float(st.strikeouts_per_9_inn or 0)
                ks  = round(k9 * ip / 9) if ip else 0
                pitchers.append({
                    "name": name,
                    "era":  st.era   or "-",
                    "w":    st.wins  or 0,
                    "l":    st.losses or 0,
                    "ip":   st.innings_pitched or "-",
                    "k":    ks,
                    "bb":   st.base_on_balls or 0,
                    "whip": st.whip or "-",
                })
            except Exception:
                pitchers.append({"name": name, "era": "-", "w": 0, "l": 0, "ip": "-", "k": 0, "bb": 0, "whip": "-"})
        else:
            try:
                s = mlb.get_player_stats(pid, stats=['season'], groups=['hitting'])
                st = s['hitting']['season'].splits[0].stat
                hitters.append({
                    "name": name,
                    "pos":  pos_abbr or pos_type[:2],
                    "avg":  st.avg  or "-",
                    "hr":   st.home_runs or 0,
                    "rbi":  st.rbi  or 0,
                    "r":    st.runs or 0,
                    "ops":  st.ops  or "-",
                    "sb":   st.stolen_bases or 0,
                })
            except Exception:
                hitters.append({"name": name, "pos": pos_abbr, "avg": "-", "hr": 0, "rbi": 0, "r": 0, "ops": "-", "sb": 0})

    hitters.sort(key=lambda x: float(x['ops'])  if str(x['ops'])  not in ('-', '') else 0, reverse=True)
    pitchers.sort(key=lambda x: float(x['era'])  if str(x['era'])  not in ('-', '') else 99)
    return hitters, pitchers


def get_all_nl_east_games():
    """Returns {abbr: game_dict_or_None} for all NL East teams."""
    games = {}
    for tid in NL_EAST_TEAMS:
        abbr, _ = TEAM_MAP.get(tid, ("???", ""))
        games[abbr] = get_todays_game(tid)
        print(f"  {abbr}: {games[abbr]['detailed_state'] if games[abbr] else 'no game'}")
    return games


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def _base_color(occupied):
    return "#E8A020" if occupied else "rgba(255,255,255,0.15)"


def _diamond_svg(on_first, on_second, on_third):
    c1, c2, c3 = _base_color(on_first), _base_color(on_second), _base_color(on_third)
    return f'''<svg viewBox="0 0 100 100" width="72" height="72" aria-hidden="true">
  <polygon points="50,12 88,50 50,88 12,50" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="1.5"/>
  <rect x="43" y="5"  width="14" height="14" rx="2" transform="rotate(45,50,12)" fill="{c2}"/>
  <rect x="81" y="43" width="14" height="14" rx="2" transform="rotate(45,88,50)" fill="{c1}"/>
  <rect x="5"  y="43" width="14" height="14" rx="2" transform="rotate(45,12,50)" fill="{c3}"/>
  <polygon points="50,95 58,87 58,80 42,80 42,87" fill="rgba(255,255,255,0.35)"/>
</svg>'''


def _dot_row(filled, total, filled_class):
    return ''.join(
        f'<span class="count-dot {filled_class}"></span>' if i < (filled or 0)
        else '<span class="count-dot dot-empty"></span>'
        for i in range(total)
    )


# ---------------------------------------------------------------------------
# Game card renderer (works for any team)
# ---------------------------------------------------------------------------

def render_game_card(game):
    team  = game["team_abbr"]
    opp   = game["opp_abbr"]
    away_label  = team if game["team_is_away"] else opp
    home_label  = opp  if game["team_is_away"] else team
    away_score  = game["team_score"] if game["team_is_away"] else game["opp_score"]
    home_score  = game["opp_score"]  if game["team_is_away"] else game["team_score"]
    # Featured team score gets the bright color; opponent gets gold
    away_class  = "score-featured" if game["team_is_away"] else "score-opp"
    home_class  = "score-opp" if game["team_is_away"] else "score-featured"

    state  = game["abstract_state"]
    detail = game["detailed_state"]
    reason = game["reason"]
    venue  = game["venue"]
    inning = game["inning_info"]

    if state == "Preview":
        status_badge = '<span class="badge badge-upcoming">Upcoming</span>'
        score_html = f'''
            <div class="score-row">
                <span class="team-abbr">{away_label}</span>
                <span class="score-dash">vs</span>
                <span class="team-abbr">{home_label}</span>
            </div>
            <div class="game-detail">{detail}</div>'''

    elif state == "Live":
        delay_tag    = f' <span class="badge badge-delay">{reason} Delay</span>' if reason else ""
        inning_tag   = f'<div class="inning-info">{inning}</div>' if inning else ""
        status_badge = f'<span class="badge badge-live">LIVE{delay_tag}</span>'

        count_html = ""
        if game["balls"] is not None:
            count_html = f'''
            <div class="count-row">
                <div class="count-group"><span class="count-label">B</span>{_dot_row(game["balls"],   4, "dot-ball")}</div>
                <div class="count-group"><span class="count-label">S</span>{_dot_row(game["strikes"], 3, "dot-strike")}</div>
                <div class="count-group"><span class="count-label">O</span>{_dot_row(game["outs"],    3, "dot-out")}</div>
            </div>'''

        situation_html = ""
        batter  = game.get("batter_name")
        pitcher = game.get("pitcher_name")
        if batter or pitcher:
            batter_row  = f'<div class="sit-item"><span class="sit-label">At Bat</span><span class="sit-name">{batter}</span></div>'  if batter  else ""
            pitcher_row = f'<div class="sit-item"><span class="sit-label">Pitching</span><span class="sit-name">{pitcher}</span></div>' if pitcher else ""
            diamond     = _diamond_svg(game.get("on_first", False), game.get("on_second", False), game.get("on_third", False))
            situation_html = f'''
            <div class="situation-row">
                <div class="diamond-wrap">{diamond}</div>
                <div class="situation-info">{batter_row}{pitcher_row}</div>
            </div>'''

        score_html = f'''
            <div class="score-row">
                <span class="team-abbr">{away_label}</span>
                <span class="score-num {away_class}">{away_score}</span>
                <span class="score-dash">–</span>
                <span class="score-num {home_class}">{home_score}</span>
                <span class="team-abbr">{home_label}</span>
            </div>
            {inning_tag}{count_html}{situation_html}'''

    else:  # Final
        team_won     = game["team_score"] > game["opp_score"]
        result_class = "result-win" if team_won else "result-loss"
        result_word  = "W" if team_won else "L"
        status_badge = f'<span class="badge {result_class}">{result_word}</span>'
        score_html   = f'''
            <div class="score-row">
                <span class="team-abbr">{away_label}</span>
                <span class="score-num {away_class}">{away_score}</span>
                <span class="score-dash">–</span>
                <span class="score-num {home_class}">{home_score}</span>
                <span class="team-abbr">{home_label}</span>
            </div>
            <div class="game-detail">Final</div>'''

    location = f'🏠 {venue}' if not game["team_is_away"] else f'✈️ {venue}'
    return f'''
        <div class="game-card-header">
            <span class="game-card-title">{team} — Today's Game</span>
            {status_badge}
        </div>
        {score_html}
        <div class="game-location">{location}</div>'''


def render_no_game_card(team_abbr):
    return f'''
        <div class="game-card-header">
            <span class="game-card-title">{team_abbr} — Today's Game</span>
            <span class="badge badge-upcoming">Off Day</span>
        </div>
        <div class="no-game">No game today</div>'''


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_standings(standings):
    rows = ""
    for s in standings:
        base_class = "standings-braves" if s["is_braves"] else ""
        l10 = f'{s["l10"]}-{s["l10_l"]}' if s["l10"] != "-" else "-"
        rows += f'''
        <tr class="{base_class}" data-team="{s["abbr"]}" tabindex="0" role="button" aria-label="View {s["team"]} game">
            <td class="rank">{s["rank"]}</td>
            <td class="team-name">{s["team"]}</td>
            <td>{s["w"]}</td>
            <td>{s["l"]}</td>
            <td>{s["pct"]}</td>
            <td>{s["gb"]}</td>
            <td>{l10}</td>
            <td>{s["streak"]}</td>
        </tr>'''
    return f'''
    <div class="section">
        <h2 class="section-title">🏆 NL East Standings <span class="standings-hint">tap a team to see their game</span></h2>
        <div class="table-wrap">
            <table class="standings-table">
                <thead>
                    <tr>
                        <th>#</th><th class="team-name">Team</th>
                        <th>W</th><th>L</th><th>PCT</th><th>GB</th><th>L10</th><th>Streak</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>'''


def render_recent_games(games):
    rows = ""
    for g in games:
        if g["braves_score"] is None:
            continue
        is_live = g["status"] == "Live"
        won     = g["won"]
        if is_live:
            badge_class, badge_text = "badge-live", "LIVE"
        elif won:
            badge_class, badge_text = "result-win", "W"
        else:
            badge_class, badge_text = "result-loss", "L"
        opp   = g["opponent"].replace("Atlanta Braves", "ATL")
        score = f'{g["braves_score"]}–{g["opp_score"]}'
        rows += f'''
        <tr>
            <td class="game-date">{g["date"]}</td>
            <td>{g["at"]} {opp}</td>
            <td class="score-cell">{score}</td>
            <td><span class="badge {badge_class}">{badge_text}</span></td>
            <td class="game-state-label">{g["detailed_state"]}</td>
        </tr>'''
    if not rows:
        rows = '<tr><td colspan="5">No recent games found.</td></tr>'
    return f'''
    <div class="section">
        <h2 class="section-title">📋 Recent Games</h2>
        <div class="table-wrap">
            <table class="standings-table">
                <thead><tr>
                    <th>Date</th><th>Opponent</th><th>Score</th><th>Result</th><th>Status</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>'''


def render_roster(hitters, pitchers):
    hitter_rows = ""
    for h in hitters:
        hitter_rows += f'''
        <tr>
            <td class="player-name">{h["name"]}</td>
            <td class="pos-badge-cell"><span class="pos-badge">{h["pos"]}</span></td>
            <td class="stat-num">{h["avg"]}</td>
            <td class="stat-num">{h["hr"]}</td>
            <td class="stat-num">{h["rbi"]}</td>
            <td class="stat-num">{h["r"]}</td>
            <td class="stat-num">{h["ops"]}</td>
            <td class="stat-num">{h["sb"]}</td>
        </tr>'''

    pitcher_rows = ""
    for p in pitchers:
        wl = f'{p["w"]}-{p["l"]}'
        pitcher_rows += f'''
        <tr>
            <td class="player-name">{p["name"]}</td>
            <td class="stat-num era">{p["era"]}</td>
            <td class="stat-num">{wl}</td>
            <td class="stat-num">{p["ip"]}</td>
            <td class="stat-num">{p["k"]}</td>
            <td class="stat-num">{p["bb"]}</td>
            <td class="stat-num">{p["whip"]}</td>
        </tr>'''

    return f'''
    <div class="roster-section">
        <h2 class="roster-title">🏏 Hitters</h2>
        <div class="table-wrap">
            <table class="roster-table">
                <thead><tr>
                    <th class="player-name">Player</th><th>Pos</th>
                    <th>AVG</th><th>HR</th><th>RBI</th><th>R</th><th>OPS</th><th>SB</th>
                </tr></thead>
                <tbody>{hitter_rows}</tbody>
            </table>
        </div>
    </div>
    <div class="roster-section">
        <h2 class="roster-title">⚾ Pitchers</h2>
        <div class="table-wrap">
            <table class="roster-table">
                <thead><tr>
                    <th class="player-name">Player</th>
                    <th>ERA</th><th>W-L</th><th>IP</th><th>K</th><th>BB</th><th>WHIP</th>
                </tr></thead>
                <tbody>{pitcher_rows}</tbody>
            </table>
        </div>
    </div>'''


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(games_by_abbr, standings, recent_games, hitters, pitchers, updated_at):
    # Pre-render one card per NL East team
    cards_html = ""
    for abbr, game in games_by_abbr.items():
        inner   = render_game_card(game) if game else render_no_game_card(abbr)
        display = "block" if abbr == "ATL" else "none"
        cards_html += f'<div id="card-{abbr}" class="game-card" style="display:{display}">{inner}</div>\n'

    standings_html = render_standings(standings)
    recent_html    = render_recent_games(recent_games)
    roster_html    = render_roster(hitters, pitchers)

    has_live_game_js = "true" if any(
        g and g.get("abstract_state") == "Live" for g in games_by_abbr.values()
    ) else "false"

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Atlanta Braves Scores</title>
    <style>
        :root {{
            --navy: #13274F;
            --red: #CE1141;
            --gold: #EAAA00;
            --white: #FFFFFF;
            --light-bg: #F4F6FA;
            --card-bg: #FFFFFF;
            --border: #D8DCE6;
            --text: #1A1A2E;
            --muted: #6B7280;
            --braves-row: #EAF0FB;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--light-bg);
            color: var(--text);
            min-height: 100vh;
        }}
        header {{
            background: var(--navy);
            padding: 20px 24px;
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .logo {{ font-size: 2.4rem; }}
        .header-text h1 {{ color: var(--white); font-size: 1.6rem; font-weight: 800; letter-spacing: -0.02em; }}
        .header-text p  {{ color: var(--gold);  font-size: 0.85rem; font-weight: 600; margin-top: 2px; }}
        main {{
            max-width: 760px;
            margin: 0 auto;
            padding: 24px 16px 40px;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }}
        /* Game card */
        .game-card {{
            background: var(--navy);
            border-radius: 16px;
            padding: 24px;
            color: var(--white);
            box-shadow: 0 4px 20px rgba(19,39,79,0.25);
            transition: opacity .15s;
        }}
        .game-card-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }}
        .game-card-title {{ font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: rgba(255,255,255,0.6); }}
        .score-row {{ display: flex; align-items: center; justify-content: center; gap: 16px; margin: 8px 0; }}
        .team-abbr {{ font-size: 1.6rem; font-weight: 900; letter-spacing: 0.04em; }}
        .score-num {{ font-size: 3.8rem; font-weight: 900; line-height: 1; color: var(--gold); }}
        .score-featured {{ color: #FFFFFF; }}
        .score-opp      {{ color: var(--gold); }}
        .score-dash {{ font-size: 2rem; color: rgba(255,255,255,0.4); font-weight: 300; }}
        .inning-info {{ text-align: center; font-size: 1rem; color: rgba(255,255,255,0.7); margin-top: 8px; font-weight: 600; }}
        .count-row {{ display: flex; justify-content: center; gap: 20px; margin-top: 14px; }}
        .count-group {{ display: flex; align-items: center; gap: 6px; }}
        .count-label {{ font-size: 0.7rem; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(255,255,255,0.45); width: 12px; }}
        .count-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
        .dot-ball {{ background: #22C55E; }}
        .dot-strike {{ background: #EF4444; }}
        .dot-out {{ background: #F59E0B; }}
        .dot-empty {{ background: rgba(255,255,255,0.15); }}
        .situation-row {{ display: flex; align-items: center; justify-content: center; gap: 20px; margin-top: 16px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.08); }}
        .situation-info {{ display: flex; flex-direction: column; gap: 8px; }}
        .sit-item {{ display: flex; flex-direction: column; gap: 1px; }}
        .sit-label {{ font-size: 0.62rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(255,255,255,0.4); }}
        .sit-name {{ font-size: 0.9rem; font-weight: 700; color: rgba(255,255,255,0.9); }}
        .game-detail {{ text-align: center; font-size: 0.9rem; color: rgba(255,255,255,0.6); margin-top: 6px; }}
        .game-location {{ text-align: center; font-size: 0.82rem; color: rgba(255,255,255,0.5); margin-top: 12px; }}
        .no-game {{ text-align: center; font-size: 1.2rem; padding: 16px 0; color: rgba(255,255,255,0.7); }}
        /* Badges */
        .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.72rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; }}
        .badge-live {{ background: var(--red); color: var(--white); }}
        .badge-delay {{ background: #F59E0B; color: #1A1A00; margin-left: 6px; }}
        .badge-upcoming {{ background: rgba(255,255,255,0.15); color: rgba(255,255,255,0.8); }}
        .result-win {{ background: #16A34A; color: var(--white); }}
        .result-loss {{ background: var(--red); color: var(--white); }}
        /* Sections */
        .section {{ background: var(--card-bg); border-radius: 14px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .section-title {{ font-size: 1rem; font-weight: 800; color: var(--navy); margin-bottom: 14px; letter-spacing: -0.01em; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
        .standings-hint {{ font-size: 0.72rem; font-weight: 500; color: var(--muted); letter-spacing: 0; }}
        /* Tables */
        .table-wrap {{ overflow-x: auto; }}
        .standings-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
        .standings-table th {{ text-align: left; padding: 8px 10px; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); border-bottom: 2px solid var(--border); }}
        .standings-table td {{ padding: 10px 10px; border-bottom: 1px solid var(--border); color: var(--text); }}
        .standings-table tr:last-child td {{ border-bottom: none; }}
        .standings-table .team-name {{ font-weight: 600; min-width: 160px; }}
        .standings-table .rank {{ color: var(--muted); width: 28px; }}
        .standings-braves td {{ background: var(--braves-row); font-weight: 700; }}
        .standings-braves .team-name {{ color: var(--navy); }}
        /* Clickable rows */
        tr[data-team] {{ cursor: pointer; transition: background .12s; }}
        tr[data-team]:hover td {{ background: #dde8f8; }}
        tr[data-team]:focus {{ outline: 2px solid var(--navy); outline-offset: -2px; }}
        tr.standings-active td {{ background: #c8daF8 !important; }}
        tr.standings-active .team-name {{ color: var(--navy); font-weight: 800; }}
        .game-date {{ color: var(--muted); font-size: 0.82rem; white-space: nowrap; }}
        .score-cell {{ font-weight: 700; }}
        .game-state-label {{ color: var(--muted); font-size: 0.82rem; }}
        footer {{ text-align: center; padding: 16px; font-size: 0.78rem; color: var(--muted); }}
        /* Tabs */
        .tab-bar {{ background: var(--navy); padding: 0 24px; display: flex; gap: 4px; }}
        .tab-btn {{
            background: none; border: none; cursor: pointer;
            color: rgba(255,255,255,0.5); font-size: 0.85rem; font-weight: 700;
            padding: 12px 16px; border-bottom: 3px solid transparent;
            transition: color .15s, border-color .15s;
        }}
        .tab-btn:hover {{ color: rgba(255,255,255,0.8); }}
        .tab-btn.active {{ color: #fff; border-bottom-color: var(--red); }}
        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: flex; flex-direction: column; gap: 24px; }}
        /* Roster tables */
        .roster-section {{ background: var(--card-bg); border-radius: 14px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .roster-title {{ font-size: 1rem; font-weight: 800; color: var(--navy); margin-bottom: 14px; }}
        .roster-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
        .roster-table th {{ text-align: right; padding: 6px 10px 10px; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); border-bottom: 2px solid var(--border); white-space: nowrap; }}
        .roster-table th.player-name {{ text-align: left; min-width: 140px; }}
        .roster-table td {{ padding: 10px 10px; border-bottom: 1px solid var(--border); }}
        .roster-table tr:last-child td {{ border-bottom: none; }}
        .roster-table tr:hover td {{ background: #f0f4fb; }}
        .player-name {{ font-weight: 600; text-align: left; }}
        .pos-badge-cell {{ text-align: left; }}
        .pos-badge {{ display: inline-block; background: var(--braves-row); color: var(--navy); font-size: 0.65rem; font-weight: 800; letter-spacing: 0.06em; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; }}
        .stat-num {{ text-align: right; font-variant-numeric: tabular-nums; color: var(--text); }}
        .stat-num.era {{ font-weight: 700; color: var(--navy); }}
    </style>
</head>
<body>
    <header>
        <span class="logo">🪓</span>
        <div class="header-text">
            <h1>Atlanta Braves</h1>
            <p>2026 Season Tracker</p>
        </div>
    </header>
    <nav class="tab-bar">
        <button class="tab-btn active" onclick="showTab('scores', this)">Scores</button>
        <button class="tab-btn"        onclick="showTab('roster', this)">Roster &amp; Stats</button>
    </nav>
    <main>
        <div id="tab-scores" class="tab-panel active">
            <div id="game-cards">
{cards_html}
            </div>
            {standings_html}
            {recent_html}
        </div>
        <div id="tab-roster" class="tab-panel">
            {roster_html}
        </div>
    </main>
    <footer>Last updated: {updated_at} &nbsp;·&nbsp; Data via MLB Stats API</footer>
    <script>
        function showTab(name, btn) {{
            document.querySelectorAll('.tab-panel').forEach(function(el) {{ el.classList.remove('active'); }});
            document.getElementById('tab-' + name).classList.add('active');
            document.querySelectorAll('.tab-btn').forEach(function(el) {{ el.classList.remove('active'); }});
            btn.classList.add('active');
        }}
    </script>
    <script>
        function showTeam(abbr) {{
            document.querySelectorAll('#game-cards .game-card').forEach(el => el.style.display = 'none');
            var card = document.getElementById('card-' + abbr);
            if (card) card.style.display = 'block';
            document.querySelectorAll('tr[data-team]').forEach(el => el.classList.remove('standings-active'));
            var row = document.querySelector('tr[data-team="' + abbr + '"]');
            if (row) row.classList.add('standings-active');
        }}
        // Mark ATL as active on load
        var atlRow = document.querySelector('tr[data-team="ATL"]');
        if (atlRow) atlRow.classList.add('standings-active');
        // Wire up clicks
        document.querySelectorAll('tr[data-team]').forEach(function(tr) {{
            tr.addEventListener('click', function() {{ showTeam(tr.dataset.team); }});
            tr.addEventListener('keydown', function(e) {{ if (e.key === 'Enter' || e.key === ' ') showTeam(tr.dataset.team); }});
        }});
    </script>
    <script>
        // Auto-reload: every 60s when a game is live, every 5 min otherwise.
        // has_live_game is baked in by generate.py at build time.
        var hasLiveGame = {has_live_game_js};
        setTimeout(function() {{ location.reload(); }}, hasLiveGame ? 60000 : 300000);
    </script>
</body>
</html>
'''


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys, os

    print("Fetching data...")
    games_by_abbr    = get_all_nl_east_games()
    standings        = get_standings()
    recent           = get_recent_games(6)
    print("  Fetching roster stats (this takes ~20s)...")
    hitters, pitchers = get_roster_stats()
    updated_at       = datetime.now().strftime("%B %d, %Y at %-I:%M %p")

    print(f"  Standings: {len(standings)} NL East teams")
    print(f"  Recent games: {len(recent)} loaded")
    print(f"  Roster: {len(hitters)} hitters, {len(pitchers)} pitchers")

    html = build_html(games_by_abbr, standings, recent, hitters, pitchers, updated_at)

    # Skip write if nothing changed (keeps git history clean in CI).
    if os.path.exists("index.html"):
        with open("index.html", "r") as f:
            if f.read() == html:
                print("\nNo changes — index.html is already up to date.")
                sys.exit(0)

    with open("index.html", "w") as f:
        f.write(html)

    print("\nDone! Wrote index.html")
    print("Next: git add index.html && git commit -m 'update scores' && git push")
