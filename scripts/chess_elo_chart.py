#!/usr/bin/env python3
import os
import sys
import time
import json
import math
import pathlib
import datetime as dt
from dataclasses import dataclass
from typing import List, Tuple
import pathlib
from pathlib import Path

import requests
import pandas as pd
import matplotlib.pyplot as plt

API_ROOT = "https://api.chess.com/pub"
PALETTE = {
    "green": "#69923e",
    "green_dark": "#4e7837",
    "bg": "#2c2b29",
    "grid": "#4b4847",
    "fg": "#ffffff",
}

@dataclass(frozen=True)
class GamePoint:
    when: dt.datetime
    rating: int

class ChessComClient:
    def __init__(self, username: str, session: requests.Session | None = None):
        self.username = username.lower()
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": f"chess-elo-chart ({self.username}) - contact: {os.getenv('CONTACT_EMAIL','n/a')}"})

    def list_archives(self) -> List[str]:
        url = f"{API_ROOT}/player/{self.username}/games/archives"
        r = self.s.get(url, timeout=30)
        r.raise_for_status()
        return r.json().get("archives", [])

    def list_games_in_archive(self, archive_url: str) -> list:
        r = self.s.get(archive_url, timeout=30)
        r.raise_for_status()
        return r.json().get("games", [])

class EloSeriesBuilder:
    def __init__(self, username: str, time_class: str = "rapid"):
        self.username = username.lower()
        self.time_class = time_class

    def extract_points(self, games: list) -> List[GamePoint]:
        out: List[GamePoint] = []
        for g in games:
            if g.get("time_class") != self.time_class:
                continue
            if not g.get("rated", False):
                continue
            end_ts = g.get("end_time")
            if not isinstance(end_ts, (int, float)):
                continue
            who = "white" if g.get("white", {}).get("username", "").lower() == self.username else \
                  "black" if g.get("black", {}).get("username", "").lower() == self.username else None
            if who is None:
                continue
            rating = g.get(who, {}).get("rating")
            if isinstance(rating, int) and rating > 0:
                out.append(GamePoint(when=dt.datetime.utcfromtimestamp(end_ts), rating=rating))
        return out

    def to_daily_series(self, points: List[GamePoint]) -> pd.Series:
        if not points:
            return pd.Series(dtype="float64")
        df = pd.DataFrame({"when": [p.when for p in points], "rating": [p.rating for p in points]})
        df = df.sort_values("when")
        df["day"] = df["when"].dt.floor("D")
        last_per_day = df.groupby("day")["rating"].last()
        idx = pd.date_range(start=last_per_day.index.min(), end=dt.datetime.utcnow().date(), freq="D")
        s = last_per_day.reindex(idx).ffill()
        return s

class ChartRenderer:
    def __init__(self, palette: dict = PALETTE):
        self.p = palette

    def render_svg(self, series: pd.Series, out_path: pathlib.Path, title: str = "Rapid rating"):
        if series.empty:
            out_path.write_text("<svg xmlns='http://www.w3.org/2000/svg' width='800' height='240'></svg>")
            return
        plt.figure(figsize=(9.5, 3.2), dpi=150)
        ax = plt.gca()
        ax.set_facecolor(self.p["bg"])
        plt.plot(series.index, series.values, linewidth=2.2, color=self.p["green"])
        ax.spines[:].set_visible(False)
        ax.tick_params(colors=self.p["fg"], labelsize=9)
        ax.grid(True, alpha=0.25, color=self.p["grid"], linewidth=0.8)
        plt.title(title, color=self.p["fg"], fontsize=12, pad=10)
        plt.tight_layout()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out_path, format="svg", bbox_inches="tight")
        plt.close()

def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]

def main():
    username = os.getenv("CHESS_USERNAME", "chamzert")
    root = repo_root()
    assets_dir = root / os.getenv("ASSETS_DIR", "assets")
    assets_dir.mkdir(parents=True, exist_ok=True)
    out_svg = assets_dir / "chess-elo.svg"
    csv_path = assets_dir / "chess-elo.csv"


    client = ChessComClient(username)
    archives = client.list_archives()

    archives = sorted(archives)[-18:]

    builder = EloSeriesBuilder(username=username, time_class="rapid")
    points: List[GamePoint] = []
    for a in archives:
        for g in client.list_games_in_archive(a):
            points.extend(builder.extract_points([g]))

    series = builder.to_daily_series(points)
    if not series.empty:
        series.to_csv(csv_path, header=["rating"])
    ChartRenderer().render_svg(series, out_svg, title="Rapid rating")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
