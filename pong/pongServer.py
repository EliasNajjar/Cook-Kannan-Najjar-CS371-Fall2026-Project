"""Own the game state and simulate one two-player Pong match."""

import socket
import threading
import time

import pygame

from assets.code.network import receiveMessage, sendMessage


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
        self.paddles[side].y = max(10, min(self.height - 60, y))

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
            paddle = self.paddles[side]
            if self.ball.colliderect(paddle):
                if side == "left":
                    self.ball.left = paddle.right
                else:
                    self.ball.right = paddle.left
                x = float(self.ball.x)
                self.xVel *= -1
                self.yVel = (self.ball.centery - paddle.centery) // 2
                self.bounces += 1

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


class PongServer:
    def __init__(self) -> None:
        self.game = Game()
        self.clients: dict[str, socket.socket] = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def simulate(self) -> None:
        """Run independently of either client's rendering or network rate."""
        deadline = time.monotonic()
        while not self.stopped.is_set():
            with self.lock:
                if len(self.clients) == 2:
                    self.game.update()
            deadline += 1 / 60
            self.stopped.wait(max(0, deadline - time.monotonic()))
            if time.monotonic() - deadline > 1 / 60:
                deadline = time.monotonic()

    def handleClient(self, conn: socket.socket, side: str) -> None:
        try:
            with conn, conn.makefile("rb") as stream:
                sendMessage(conn, {"type": "hello", "width": self.game.width,
                                   "height": self.game.height, "side": side})
                while not self.stopped.is_set():
                    message = receiveMessage(stream)
                    if message.get("type") != "paddle" or type(message.get("y")) is not int:
                        raise ValueError("Expected a paddle position")
                    with self.lock:
                        self.game.setPaddle(side, message["y"])
                        state = self.game.snapshot(len(self.clients) == 2)
                    sendMessage(conn, state)
        except (OSError, ValueError, EOFError):
            pass
        finally:
            with self.lock:
                self.clients.pop(side, None)
                # Keep the remaining player connected, waiting for a fresh match.
                self.game = Game()

    def serve(self, ip: str = "0.0.0.0", port: int = 65432) -> None:
        simulation = threading.Thread(target=self.simulate, daemon=True)
        simulation.start()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((ip, port))
                server.listen()
                server.settimeout(1)
                print(f"Pong server listening on {ip}:{port}")
                while not self.stopped.is_set():
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        continue
                    conn.settimeout(5)
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    with self.lock:
                        side = next((s for s in ("left", "right") if s not in self.clients), None)
                        if side is not None:
                            self.clients[side] = conn
                    if side is None:
                        with conn:
                            try:
                                sendMessage(conn, {"type": "error", "message": "The game is full."})
                            except OSError:
                                pass
                        continue
                    threading.Thread(target=self.handleClient, args=(conn, side), daemon=True).start()
        finally:
            self.stopped.set()
            with self.lock:
                for conn in self.clients.values():
                    try:
                        conn.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            simulation.join()


if __name__ == "__main__":
    try:
        PongServer().serve()
    except KeyboardInterrupt:
        pass
