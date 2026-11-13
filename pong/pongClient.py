# =================================================================================================
# Contributing Authors:	    <Anyone who touched the code>
# Email Addresses:          <Your uky.edu email addresses>
# Date:                     <The date the file was last edited>
# Purpose:                  <How this file contributes to the project>
# Misc:                     <Not Required.  Anything else you might want to include>
# =================================================================================================

import pygame
import tkinter as tk
import socket
import threading
from pathlib import Path
from typing import BinaryIO

from assets.code.helperCode import Paddle, updateScore
from assets.code.network import receiveMessage, sendMessage

ASSETS = Path(__file__).resolve().parent / "assets"


class ServerConnection:
    """Exchange paddle positions and snapshots without blocking the display."""

    def __init__(self, client: socket.socket, stream: BinaryIO, startY: int) -> None:
        self.client = client
        self.stream = stream
        self.y = startY
        self.state: dict | None = None
        self.error = ""
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.exchange, daemon=True)

    def exchange(self) -> None:
        try:
            while not self.stopped.is_set():
                with self.lock:
                    y = self.y
                sendMessage(self.client, {"type": "paddle", "y": y})
                state = receiveMessage(self.stream)
                if state.get("type") != "state":
                    raise ValueError("Expected game state from server")
                with self.lock:
                    self.state = state
                self.stopped.wait(1 / 60)
        except (OSError, ValueError, EOFError) as error:
            with self.lock:
                self.error = f"Connection lost: {error}"

    def close(self) -> None:
        self.stopped.set()
        try:
            self.client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.thread.join()


def playGame(screenWidth: int, screenHeight: int, playerPaddle: str,
             client: socket.socket, stream: BinaryIO) -> None:
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.init()
    WHITE = (255, 255, 255)
    clock = pygame.time.Clock()
    scoreFont = pygame.font.Font(str(ASSETS / "fonts/pong-score.ttf"), 32)
    winFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 48)
    statusFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 24)
    pointSound = pygame.mixer.Sound(str(ASSETS / "sounds/point.wav"))
    bounceSound = pygame.mixer.Sound(str(ASSETS / "sounds/bounce.wav"))
    screen = pygame.display.set_mode((screenWidth, screenHeight))
    pygame.display.set_caption(f"Pong - {playerPaddle} player")
    topWall = pygame.Rect(-10, 0, screenWidth + 20, 10)
    bottomWall = pygame.Rect(-10, screenHeight - 10, screenWidth + 20, 10)
    centerLine = [pygame.Rect(screenWidth // 2 - 5, y, 5, 5)
                  for y in range(0, screenHeight, 10)]
    leftPaddle = Paddle(pygame.Rect(10, screenHeight // 2 - 25, 10, 50))
    rightPaddle = Paddle(pygame.Rect(screenWidth - 20, screenHeight // 2 - 25, 10, 50))
    paddles = {"left": leftPaddle, "right": rightPaddle}
    playerPaddleObj = paddles[playerPaddle]
    opponentSide = "right" if playerPaddle == "left" else "left"
    ball = pygame.Rect(screenWidth // 2, screenHeight // 2, 5, 5)
    connection = ServerConnection(client, stream, playerPaddleObj.rect.y)
    connection.thread.start()
    lastPoints = lastBounces = 0
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
            if not running:
                break

            # Only the local paddle is simulated here. Everything else is a snapshot.
            keys = pygame.key.get_pressed()
            movement = int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP])
            playerPaddleObj.rect.y = max(10, min(screenHeight - 60,
                playerPaddleObj.rect.y + movement * playerPaddleObj.speed))
            with connection.lock:
                connection.y = playerPaddleObj.rect.y
                state = connection.state
                error = connection.error

            lScore = rScore = 0
            winner = None
            status = "Connecting..."
            if state is not None:
                paddles[opponentSide].rect.topleft = state["paddles"][opponentSide]
                ball.topleft = state["ball"]
                lScore, rScore = state["score"]["left"], state["score"]["right"]
                winner = state["winner"]
                status = "" if state["ready"] else "Waiting for opponent..."
                if state["points"] > lastPoints:
                    pointSound.play()
                if state["bounces"] > lastBounces:
                    bounceSound.play()
                lastPoints, lastBounces = state["points"], state["bounces"]
            if error:
                status = "Disconnected - close window to rejoin"

            screen.fill((0, 0, 0))
            for rect in centerLine + [topWall, bottomWall, leftPaddle.rect, rightPaddle.rect]:
                pygame.draw.rect(screen, WHITE, rect)
            if winner:
                text = "Player 1 Wins!" if winner == "left" else "Player 2 Wins!"
                surface = winFont.render(text, False, WHITE, (0, 0, 0))
                screen.blit(surface, surface.get_rect(center=(screenWidth // 2, screenHeight // 2)))
            else:
                pygame.draw.rect(screen, WHITE, ball)
            if status:
                surface = statusFont.render(status, False, WHITE, (0, 0, 0))
                screen.blit(surface, surface.get_rect(center=(screenWidth // 2, screenHeight - 35)))
            updateScore(lScore, rScore, screen, WHITE, scoreFont)
            pygame.display.update()
            clock.tick(60)
    finally:
        connection.close()
        pygame.quit()


def joinServer(ip: str, port: str, errorLabel: tk.Label, app: tk.Tk) -> None:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    stream = None
    try:
        client.connect((ip, int(port)))
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        stream = client.makefile("rb")
        hello = receiveMessage(stream)
        if hello.get("type") == "error":
            raise ValueError(hello["message"])
        if hello.get("type") != "hello" or hello.get("side") not in ("left", "right"):
            raise ValueError("Invalid server greeting")
    except (OSError, ValueError, EOFError, OverflowError) as error:
        if stream is not None:
            stream.close()
        client.close()
        errorLabel.config(text=str(error))
        return

    app.withdraw()
    try:
        playGame(hello["width"], hello["height"], hello["side"], client, stream)
    finally:
        stream.close()
        client.close()
        app.destroy()


# This displays the opening screen, you don't need to edit this (but may if you like)
def startScreen() -> None:
    app = tk.Tk()
    app.title("Server Info")

    image = tk.PhotoImage(file=str(ASSETS / "images/logo.png"))

    titleLabel = tk.Label(image=image)
    titleLabel.grid(column=0, row=0, columnspan=2)

    ipLabel = tk.Label(text="Server IP:")
    ipLabel.grid(column=0, row=1, sticky="W", padx=8)

    ipEntry = tk.Entry(app)
    ipEntry.grid(column=1, row=1)

    portLabel = tk.Label(text="Server Port:")
    portLabel.grid(column=0, row=2, sticky="W", padx=8)

    portEntry = tk.Entry(app)
    portEntry.grid(column=1, row=2)

    errorLabel = tk.Label(text="")
    errorLabel.grid(column=0, row=4, columnspan=2)

    joinButton = tk.Button(text="Join", command=lambda: joinServer(ipEntry.get(), portEntry.get(), errorLabel, app))
    joinButton.grid(column=0, row=3, columnspan=2)

    app.mainloop()

if __name__ == "__main__":
    startScreen()
