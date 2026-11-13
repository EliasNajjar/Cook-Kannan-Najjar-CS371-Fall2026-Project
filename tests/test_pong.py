"""Physics and TCP integration checks for server-owned game state."""

import io
import os
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pong"))
from pongServer import Game, PongServer
from assets.code.network import receiveMessage, sendMessage
import pongClient
import pygame


class GameTests(unittest.TestCase):
    def test_paddle_positions_are_clamped(self) -> None:
        game = Game()
        game.setPaddle("left", -100)
        game.setPaddle("right", 10000)
        self.assertEqual(game.paddles["left"].y, 10)
        self.assertEqual(game.paddles["right"].y, 420)

    def test_paddles_and_walls_bounce(self) -> None:
        for side, x, velocity in (("left", 21, -5), ("right", 614, 5)):
            with self.subTest(side=side):
                game = Game()
                game.ball.topleft = (x, 225)
                game.xVel = velocity
                game.update()
                self.assertEqual(game.xVel, -velocity)
                self.assertEqual(game.bounces, 1)
                self.assertFalse(game.ball.colliderect(game.paddles[side]))
        for y, velocity in ((10, -12), (465, 12)):
            with self.subTest(y=y):
                game = Game()
                game.ball.y = y
                game.yVel = velocity
                game.update()
                self.assertEqual(game.yVel, -velocity)
                self.assertEqual(game.bounces, 1)
                self.assertGreaterEqual(game.ball.top, 10)
                self.assertLessEqual(game.ball.bottom, 470)

    def test_scores_reset_ball_and_stop_at_five(self) -> None:
        for side, x, velocity in (("left", 640, 5), ("right", 0, -5)):
            with self.subTest(side=side):
                game = Game()
                for _ in range(5):
                    game.ball.topleft = (x, 100)
                    game.xVel = velocity
                    game.update()
                    self.assertEqual(game.ball.topleft, (320, 240))
                self.assertEqual(game.winner(), side)
                self.assertEqual(game.score[side], 5)
                self.assertEqual(game.points, 5)
                snapshot = game.snapshot(True)
                game.update()
                self.assertEqual(game.snapshot(True), snapshot)

    def test_framing_preserves_combined_messages(self) -> None:
        stream = io.BytesIO(b'{"type":"paddle","y":100}\n{"type":"paddle","y":200}\n')
        self.assertEqual(receiveMessage(stream)["y"], 100)
        self.assertEqual(receiveMessage(stream)["y"], 200)
        with self.assertRaises(EOFError):
            receiveMessage(stream)


class ClientTests(unittest.TestCase):
    def test_client_renders_server_state_and_sends_only_own_position(self) -> None:
        client, server = socket.socketpair()
        client.settimeout(2)
        server.settimeout(2)
        messages = []
        state = Game().snapshot(True)
        state.update(ball=[123, 234], score={"left": 2, "right": 1})
        state["paddles"]["right"] = [620, 300]

        def reply() -> None:
            try:
                with server, server.makefile("rb") as stream:
                    while True:
                        messages.append(receiveMessage(stream))
                        sendMessage(server, state)
            except (EOFError, OSError):
                pass

        worker = threading.Thread(target=reply)
        worker.start()
        rendered = []
        frames = 0
        draw = pygame.draw.rect

        def capture(screen, color, rect) -> pygame.Rect:
            rendered.append(tuple(rect))
            return draw(screen, color, rect)

        def events() -> list:
            nonlocal frames
            frames += 1
            return [pygame.event.Event(pygame.QUIT)] if frames > 12 else []

        try:
            with client, client.makefile("rb") as stream:
                with patch.object(pygame.event, "get", side_effect=events), \
                     patch.object(pygame.key, "get_pressed", return_value={pygame.K_DOWN: True, pygame.K_UP: False}), \
                     patch.object(pygame.draw, "rect", side_effect=capture), \
                     patch.object(pongClient, "updateScore", wraps=pongClient.updateScore) as scores:
                    pongClient.playGame(640, 480, "left", client, stream)
                self.assertTrue(any(call.args[:2] == (2, 1) for call in scores.call_args_list))
            self.assertIn((123, 234, 5, 5), rendered)
            self.assertIn((620, 300, 10, 50), rendered)
            self.assertTrue(messages)
            self.assertTrue(all(set(message) == {"type", "y"} for message in messages))
            self.assertGreater(messages[-1]["y"], messages[0]["y"])
        finally:
            client.close()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())


class NetworkTests(unittest.TestCase):
    def test_two_clients_share_state_and_disconnect_resets_match(self) -> None:
        server = PongServer()
        # Pick an available local port for a real TCP server.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        thread = threading.Thread(target=server.serve, args=("127.0.0.1", port))
        thread.start()
        sockets = []
        streams = []

        def connect() -> tuple:
            deadline = time.monotonic() + 3
            while True:
                try:
                    conn = socket.create_connection(("127.0.0.1", port), timeout=2)
                    break
                except ConnectionRefusedError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            sockets.append(conn)
            stream = conn.makefile("rb")
            streams.append(stream)
            return conn, stream, receiveMessage(stream)

        try:
            left, leftStream, hello = connect()
            self.assertEqual(hello["side"], "left")
            sendMessage(left, {"type": "paddle", "y": 100})
            waiting = receiveMessage(leftStream)
            self.assertFalse(waiting["ready"])
            self.assertEqual(waiting["ball"], [320, 240])
            right, rightStream, hello = connect()
            self.assertEqual(hello["side"], "right")
            _, _, rejection = connect()
            self.assertEqual(rejection["type"], "error")

            # Fragment one message, and combine it with another in a single write.
            right.sendall(b'{"type":"paddle",')
            right.sendall(b'"y":300}\n{"type":"paddle","y":310}\n')
            self.assertEqual(receiveMessage(rightStream)["paddles"]["left"], [10, 100])
            self.assertEqual(receiveMessage(rightStream)["paddles"]["right"], [620, 310])
            # Scores and ball positions supplied by clients are ignored.
            sendMessage(left, {"type": "paddle", "y": 110, "score": {"left": 99}, "ball": [0, 0]})
            state = receiveMessage(leftStream)
            self.assertEqual(state["score"], {"left": 0, "right": 0})
            self.assertEqual(state["paddles"]["right"], [620, 310])
            with server.lock:
                tick = server.game.tick
            time.sleep(0.06)
            with server.lock:
                self.assertGreater(server.game.tick, tick)
                # Force a point, and verify both clients receive the same result.
                server.game.ball.topleft = (640, 100)
                server.game.xVel = 5
                server.game.update()
            for conn, stream in ((left, leftStream), (right, rightStream)):
                sendMessage(conn, {"type": "paddle", "y": 150})
                self.assertEqual(receiveMessage(stream)["score"], {"left": 1, "right": 0})

            right.shutdown(socket.SHUT_RDWR)
            deadline = time.monotonic() + 2
            while True:
                sendMessage(left, {"type": "paddle", "y": 100})
                state = receiveMessage(leftStream)
                if not state["ready"]:
                    break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            self.assertEqual(state["score"], {"left": 0, "right": 0})
            self.assertEqual(state["ball"], [320, 240])
            _, _, hello = connect()
            self.assertEqual(hello["side"], "right")
        finally:
            server.stopped.set()
            for conn in sockets:
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            for stream in streams:
                stream.close()
            for conn in sockets:
                conn.close()
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
