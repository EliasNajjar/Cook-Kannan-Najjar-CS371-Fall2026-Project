# =================================================================================================
# Contributing Authors: Hayden Cook, Mohandass Kannan, and Elias Najjar
# Email Addresses: hwco227@uky.edu, mka377@uky.edu, and esna222@uky.edu
# Date: November 22, 2026
# Purpose: Simulate game, handle clients, and host leaderboard
# =================================================================================================

import argparse
import hashlib
import hmac
import secrets
import socket
import json
from typing import BinaryIO
import threading
import time
import re
from collections import deque
from dataclasses import dataclass, field
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pygame

from cryptography.fernet import Fernet, InvalidToken


# Shared key for the LAN demo. Anyone with the client has access to this key.
FERNET = Fernet(b"xpg5hCKM6RP-Fxp71EQymasFcJ4gsZL-RkpaEwPUCiw=")
MAX_TOKEN_LINE = 8192


def sendMessage(conn: socket.socket, message: dict) -> None:
    payload = json.dumps(message).encode("utf-8")
    conn.sendall(FERNET.encrypt(payload) + b"\n")

def receiveMessage(stream: BinaryIO) -> dict:
    # A buffered reader preserves extra messages and joins fragmented TCP reads.
    line = stream.readline(MAX_TOKEN_LINE + 1)
    if not line:
        raise EOFError("Server or player disconnected")
    if len(line) > MAX_TOKEN_LINE or not line.endswith(b"\n"):
        raise ValueError("Invalid message length")
    try:
        payload = FERNET.decrypt(line[:-1])
    except InvalidToken as error:
        raise ValueError("Invalid encrypted message") from error
    message = json.loads(payload)
    if not isinstance(message, dict):
        raise ValueError("Expected a JSON object")
    return message


class Game:
    width = 640
    height = 480

    def __init__(self) -> None:
        self.paddles = {
            "left": pygame.Rect(10, 215, 10, 50),
            "right": pygame.Rect(620, 215, 10, 50),
        }
        self.score = {"left": 0, "right": 0}
        self.ball = pygame.Rect(320, 240, 5, 5)
        self.xVel = -5
        self.yVel = 0
        self.bounces = 0
        self.points = 0
        self.tick = 0

    def setPaddle(self, side: str, y: int) -> None:
        """Accept the client's position, clamped to the court."""
        self.paddles[side].y = max(10, min(self.height - 60, y))

    def bounceOffPaddle(self, side: str) -> bool:
        """Resolve a paddle collision; return whether the ball was moved."""
        paddle = self.paddles[side]
        if not self.ball.colliderect(paddle):
            return False
        if side == "left":
            self.ball.left = paddle.right
        else:
            self.ball.right = paddle.left
        self.xVel *= -1
        self.yVel = (self.ball.centery - paddle.centery) // 2
        self.bounces += 1
        return True

    def resetBall(self, direction: int) -> None:
        self.ball.topleft = (self.width // 2, self.height // 2)
        self.xVel = direction * 5
        self.yVel = 0

    def winner(self) -> str | None:
        return next((side for side, score in self.score.items() if score >= 5), None)

    def update(self) -> None:
        """Advance physics once; callers serialize this with paddle updates."""
        if self.winner():
            return
        self.tick += 1
        # Substeps prevent a steep bounce from skipping a wall or paddle.
        steps = max(abs(self.xVel), abs(self.yVel), 1)
        x, y = float(self.ball.x), float(self.ball.y)
        for _ in range(steps):
            x += self.xVel / steps
            y += self.yVel / steps
            self.ball.topleft = (round(x), round(y))
            if self.ball.x > self.width or self.ball.x < 0:
                scorer = "left" if self.ball.x > self.width else "right"
                self.score[scorer] += 1
                self.points += 1
                self.resetBall(-1 if scorer == "left" else 1)
                return

            side = "left" if self.xVel < 0 else "right"
            if self.bounceOffPaddle(side):
                x = float(self.ball.x)

            if self.ball.top < 10 and self.yVel < 0:
                self.ball.top = 10
                y = float(self.ball.y)
                self.yVel *= -1
                self.bounces += 1
            elif self.ball.bottom > self.height - 10 and self.yVel > 0:
                self.ball.bottom = self.height - 10
                y = float(self.ball.y)
                self.yVel *= -1
                self.bounces += 1

    def snapshot(self, ready: bool) -> dict:
        return {
            "type": "state",
            "paddles": {side: list(rect.topleft) for side, rect in self.paddles.items()},
            "ball": list(self.ball.topleft),
            "score": dict(self.score),
            "winner": self.winner(),
            "ready": ready,
            "tick": self.tick,
            "bounces": self.bounces,
            "points": self.points,
        }


@dataclass(eq=False)
class Player:
    conn: socket.socket
    username: str
    initials: str
    match: "Match | None" = None
    side: str | None = None


@dataclass
class Match:
    number: int
    players: dict[str, Player]
    game: Game = field(default_factory=Game)
    rematch: set[str] = field(default_factory=set)
    recorded: bool = False
    round: int = 1


class PongServer:
    def __init__(self) -> None:
        self.players: dict[str, dict] = {}
        self.clients: dict[str, Player] = {}
        self.waiting: deque[Player] = deque()
        self.matches: dict[int, Match] = {}
        self.nextMatch = 1
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.httpServer: ThreadingHTTPServer | None = None

    def pairWaiting(self) -> None:
        """Called with the lock held; each player belongs to at most one match."""
        while len(self.waiting) >= 2:
            left, right = self.waiting.popleft(), self.waiting.popleft()
            match = Match(self.nextMatch, {"left": left, "right": right})
            self.nextMatch += 1
            self.matches[match.number] = match
            for side, player in match.players.items():
                player.match, player.side = match, side

    def recordWin(self, match: Match) -> None:
        winner = match.game.winner()
        if winner and not match.recorded:
            username = match.players[winner].username.casefold()
            self.players[username]["wins"] += 1
            match.recorded = True

    def simulate(self) -> None:
        deadline = time.monotonic()
        while not self.stopped.is_set():
            with self.lock:
                for match in self.matches.values():
                    match.game.update()
                    self.recordWin(match)
            deadline += 1 / 60
            self.stopped.wait(max(0, deadline - time.monotonic()))
            if time.monotonic() - deadline > 1 / 60:
                deadline = time.monotonic()

    def register(self, conn: socket.socket, message: dict) -> Player:
        username = message.get("username")
        initials = message.get("initials")
        password = message.get("password")
        if message.get("type") != "join":
            raise ValueError("Enter a username, initials and password to join.")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", username):
            raise ValueError("Username: use 1-20 letters, numbers, underscores or hyphens.")
        if not isinstance(initials, str) or not re.fullmatch(r"[A-Za-z]{1,3}", initials):
            raise ValueError("Initials: use 1-3 letters.")
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise ValueError("Password: use 1-128 characters.")
        key = username.casefold()
        initials = initials.upper()
        with self.lock:
            record = self.players.get(key)
        salt = secrets.token_bytes(16) if record is None else record["salt"]
        # Password hashing must not hold the lock used by the game simulation.
        passwordHash = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                      n=2**15, r=8, p=3, maxmem=64 * 1024**2, dklen=32)
        if record is not None:
            passwordMatches = hmac.compare_digest(passwordHash, record["password_hash"])
            if not passwordMatches or record["initials"] != initials:
                raise ValueError("Incorrect password or initials for that username.")
        with self.lock:
            if key in self.clients:
                raise ValueError("That username is already connected.")
            if self.players.get(key) is not record:
                raise ValueError("That username was just registered. Try joining again.")
            if record is None:
                record = {"username": username, "initials": initials, "wins": 0,
                          "salt": salt, "password_hash": passwordHash}
                self.players[key] = record
            player = Player(conn, record["username"], record["initials"])
            self.clients[key] = player
            self.waiting.append(player)
            self.pairWaiting()
            return player

    def stateFor(self, player: Player) -> dict:
        match = player.match
        if match is None:
            return {"type": "state", "phase": "waiting", "side": None,
                    "match_id": None, "round": 0,
                    "queue_position": list(self.waiting).index(player) + 1}
        self.recordWin(match)
        state = match.game.snapshot(True)
        opponent = match.players["right" if player.side == "left" else "left"]
        state.update(
            phase="finished" if state["winner"] else "playing",
            side=player.side, match_id=match.number, round=match.round,
            you_ready=player.side in match.rematch,
            opponent_ready=opponent.side in match.rematch,
            opponent=opponent.username,
            players={side: {"username": p.username, "initials": p.initials}
                     for side, p in match.players.items()},
        )
        return state

    def updatePlayer(self, player: Player, message: dict) -> dict:
        if message.get("type") != "update":
            raise ValueError("Expected a player update.")
        if type(message.get("y")) is not int or type(message.get("play_again")) is not bool:
            raise ValueError("Invalid player update.")
        with self.lock:
            match = player.match
            # Ignore input from a previous match or round, including stale rematch clicks.
            if (match is not None and message.get("match_id") == match.number
                    and message.get("round") == match.round):
                self.recordWin(match)
                if match.game.winner():
                    if message["play_again"]:
                        match.rematch.add(player.side)
                    if len(match.rematch) == 2:
                        match.game = Game()
                        match.rematch.clear()
                        match.recorded = False
                        match.round += 1
                else:
                    match.game.setPaddle(player.side, message["y"])
            return self.stateFor(player)

    def removePlayer(self, player: Player) -> None:
        with self.lock:
            self.clients.pop(player.username.casefold(), None)
            if player in self.waiting:
                self.waiting.remove(player)
            match = player.match
            if match is not None:
                self.recordWin(match)
                self.matches.pop(match.number, None)
                for other in match.players.values():
                    other.match, other.side = None, None
                    if other is not player:
                        self.waiting.append(other)
            self.pairWaiting()

    def handleClient(self, conn: socket.socket) -> None:
        player = None
        try:
            with conn.makefile("rb") as stream:
                # A recorded join message cannot be reused on another connection.
                nonce = secrets.token_hex(16)
                sendMessage(conn, {"type": "challenge", "nonce": nonce})
                join = receiveMessage(stream)
                if join.get("nonce") != nonce:
                    raise ValueError("Invalid join challenge.")
                player = self.register(conn, join)
                sendMessage(conn, {"type": "hello", "width": Game.width, "height": Game.height,
                                   "username": player.username, "initials": player.initials})
                while not self.stopped.is_set():
                    sendMessage(conn, self.updatePlayer(player, receiveMessage(stream)))
        except ValueError as error:
            try:
                sendMessage(conn, {"type": "error", "message": str(error)})
            except OSError:
                pass
        except (OSError, EOFError):
            pass
        finally:
            if player is not None:
                self.removePlayer(player)
            conn.close()

    def leaderboardPage(self) -> bytes:
        with self.lock:
            records = sorted(({key: p[key] for key in ("username", "initials", "wins")}
                              for p in self.players.values()),
                             key=lambda p: (-p["wins"], p["username"].casefold()))
        rows = "".join(
            f"<tr><td>{i}</td><td>{escape(p['initials'])}</td>"
            f"<td>{escape(p['username'])}</td><td>{p['wins']}</td></tr>"
            for i, p in enumerate(records, 1))
        if not rows:
            rows = '<tr><td colspan="4">No players yet. Join a game to get started.</td></tr>'
        return ("""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5"><title>Pong Leaderboard</title>
<style>
body{background:#10151e;color:#edf3ff;font-family:system-ui,sans-serif;margin:0;padding:40px 20px}
main{max-width:800px;margin:auto}h1{font-size:2.5rem;margin-bottom:8px}
p{color:#afbdd3}table{width:100%;border-collapse:collapse;background:#192232;margin-top:30px}
th,td{text-align:left;padding:16px;border-bottom:1px solid #334056}
th{color:#89e2cb}footer{margin-top:24px;color:#afbdd3;font-size:.9rem}
</style></head><body><main><h1>Pong Leaderboard</h1>
<p>Total matches won. Updates every five seconds.</p>
<table><thead><tr><th>Rank</th><th>Initials</th><th>Username</th><th>Wins</th></tr></thead>
<tbody>""" + rows + """</tbody></table>
<footer>Scores are held in memory and reset when the server restarts.</footer>
</main></body></html>""").encode("utf-8")

    def startLeaderboard(self, ip: str, port: int) -> threading.Thread:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path not in ("/", "/leaderboard"):
                    self.send_error(404)
                    return
                content = owner.leaderboardPage()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format, *args) -> None:
                pass

        self.httpServer = ThreadingHTTPServer((ip, port), Handler)
        worker = threading.Thread(target=self.httpServer.serve_forever, daemon=True)
        worker.start()
        return worker

    def serve(self, ip: str = "0.0.0.0", port: int = 65432,
              leaderboard_port: int = 80) -> None:
        workers = []
        simulation = threading.Thread(target=self.simulate, daemon=True)
        web = None
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((ip, port))
                server.listen()
                server.settimeout(0.2)
                web = self.startLeaderboard(ip, leaderboard_port)
                simulation.start()
                print(f"Pong server listening on {ip}:{server.getsockname()[1]}")
                print(f"Leaderboard listening on http://{ip}:{self.httpServer.server_port}")
                while not self.stopped.is_set():
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        continue
                    conn.settimeout(5)
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    worker = threading.Thread(target=self.handleClient, args=(conn,), daemon=True)
                    worker.start()
                    workers = [w for w in workers if w.is_alive()]
                    workers.append(worker)
        finally:
            self.stopped.set()
            with self.lock:
                connections = [p.conn for p in self.clients.values()]
            for conn in connections:
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if simulation.ident is not None:
                simulation.join()
            if self.httpServer is not None:
                self.httpServer.shutdown()
                self.httpServer.server_close()
            if web is not None:
                web.join()
            for worker in workers:
                worker.join(timeout=6)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Pong game server and leaderboard.")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on (default: all interfaces)")
    parser.add_argument("--port", type=int, default=65432, help="game port (default: 65432)")
    parser.add_argument("--leaderboard-port", type=int, default=80, help="HTTP port (default: 80)")
    args = parser.parse_args()
    for port in (args.port, args.leaderboard_port):
        if not 0 <= port <= 65535:
            parser.error("ports must be between 0 and 65535")
    try:
        PongServer().serve(args.host, args.port, args.leaderboard_port)
    except KeyboardInterrupt:
        pass
    except OSError as error:
        parser.exit(1, f"Pong server could not start or continue: {error}\n")

