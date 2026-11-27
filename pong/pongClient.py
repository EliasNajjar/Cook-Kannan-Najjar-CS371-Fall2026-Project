# =================================================================================================
# Contributing Authors:	    Mohandass Kannan, Elias Najjar, Hayden Cook
# Email Addresses:          mka377@uky.edu, esna222@uky.edu, hwco227@uky.edu
# Date:                     11/27/26
# Purpose:                  UI for the user and displaying the game.  This file is the client side of the project and is responsible for connecting to the server and sending/receiving data.
# =================================================================================================

"""Pong client with matchmaking, player names and mutual rematch controls."""

import pygame
import tkinter as tk
import socket
import json
import threading
from pathlib import Path
from typing import BinaryIO

from assets.code.helperCode import Paddle, updateScore


from cryptography.fernet import Fernet, InvalidToken


# Shared key for the LAN demo. Anyone with the client has access to this key.
FERNET = Fernet(b"xpg5hCKM6RP-Fxp71EQymasFcJ4gsZL-RkpaEwPUCiw=")
MAX_LEN = 8192


def sendMessage(client: socket.socket, message: dict) -> None:
    client.send(FERNET.encrypt(json.dumps(message).encode())) # encode and send fernet encrypted message to server

def receiveMessage(client: socket.socket) -> dict:
    return json.loads(FERNET.decrypt(client.recv(MAX_LEN))) # return decrypted and loaded dict object from server

ASSETS = Path(__file__).resolve().parent / "assets"

class Paddles:
    """Keep paddle setup, movement, snapshot updates and drawing together."""

    def __init__(self, width: int, height: int) -> None:
        self.height = height
        self.bySide = {
            "left": Paddle(pygame.Rect(10, height // 2 - 25, 10, 50)),
            "right": Paddle(pygame.Rect(width - 20, height // 2 - 25, 10, 50)),
        }
        self.token = None

    def update(self, state: dict, connected: bool) -> int:
        side = state.get("side")
        token = (state.get("match_id"), state.get("round"))
        if token != self.token:
            for paddle in self.bySide.values():
                paddle.rect.y = self.height // 2 - 25
            if side in self.bySide:
                self.bySide[side].rect.topleft = state["paddles"][side]
            self.token = token
        if side not in self.bySide:
            return self.height // 2 - 25
        # Move only our paddle locally; the opponent comes from the server.
        keys = pygame.key.get_pressed()
        movement = int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP])
        own = self.bySide[side]
        if state.get("phase") == "playing" and connected:
            own.rect.y = max(10, min(self.height - 60, own.rect.y + movement * own.speed))
        for other, paddle in self.bySide.items():
            if other != side:
                paddle.rect.topleft = state["paddles"][other]
        return own.rect.y

    def draw(self, screen: pygame.Surface, color: tuple) -> None:
        for paddle in self.bySide.values():
            pygame.draw.rect(screen, color, paddle.rect)


class ServerConnection:
    """Exchange snapshots in a background thread so the UI stays responsive."""

    def __init__(self, client: socket.socket, stream: BinaryIO, startY: int) -> None:
        self.client = client
        self.stream = stream
        self.y = startY
        self.inputToken = (None, None)
        self.state: dict | None = None
        self.rematch: tuple | None = None
        self.error = ""
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.exchange, daemon=True)

    def exchange(self) -> None:
        try:
            while not self.stopped.is_set():
                with self.lock:
                    # The position and its round come from the same rendered frame.
                    token = self.inputToken
                    message = {"type": "update", "y": self.y,
                               "match_id": token[0], "round": token[1],
                               "play_again": self.rematch is not None and self.rematch == token}
                sendMessage(self.client, message)
                state = receiveMessage(self.client)
                if state.get("type") == "error":
                    raise ValueError(state.get("message", "Server error"))
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


def rematchStatus(state: dict) -> str:
    if state.get("you_ready") and state.get("opponent_ready"):
        return "Starting next game..."
    if state.get("you_ready"):
        return "Waiting for opponent..."
    if state.get("opponent_ready"):
        return "Opponent wants to play again."
    return "Both players must click to restart."


def playGame(screenWidth: int, screenHeight: int, username: str,
             client: socket.socket, stream: BinaryIO) -> None:
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.init()
    WHITE = (255, 255, 255)
    clock = pygame.time.Clock()
    scoreFont = pygame.font.Font(str(ASSETS / "fonts/pong-score.ttf"), 32)
    winFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 40)
    statusFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 24)
    nameFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 20)
    pointSound = pygame.mixer.Sound(str(ASSETS / "sounds/point.wav"))
    bounceSound = pygame.mixer.Sound(str(ASSETS / "sounds/bounce.wav"))
    screen = pygame.display.set_mode((screenWidth, screenHeight))
    pygame.display.set_caption(f"Pong - {username}")
    topWall = pygame.Rect(-10, 0, screenWidth + 20, 10)
    bottomWall = pygame.Rect(-10, screenHeight - 10, screenWidth + 20, 10)
    centerLine = [pygame.Rect(screenWidth // 2 - 5, y, 5, 5)
                  for y in range(0, screenHeight, 10)]
    paddles = Paddles(screenWidth, screenHeight)
    ball = pygame.Rect(screenWidth // 2, screenHeight // 2, 5, 5)
    button = pygame.Rect(screenWidth // 2 - 110, screenHeight // 2 + 45, 220, 46)
    connection = ServerConnection(client, stream, screenHeight // 2 - 25)
    connection.thread.start()
    lastToken = None
    lastPoints = lastBounces = 0
    running = True

    def centered(text, font, y, color=WHITE):
        surface = font.render(text, False, color, (0, 0, 0))
        screen.blit(surface, surface.get_rect(center=(screenWidth // 2, y)))

    try:
        while running:
            with connection.lock:
                state = connection.state
                error = connection.error
            state = state or {}
            phase = state.get("phase", "connecting")
            side = state.get("side")
            token = (state.get("match_id"), state.get("round"))
            finished = phase == "finished"
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                      and button.collidepoint(event.pos) and finished and not error):
                    with connection.lock:
                        connection.rematch = token
            if not running:
                break

            if token != lastToken:
                lastPoints = lastBounces = 0
                lastToken = token

            paddleY = paddles.update(state, connected=not error)
            with connection.lock:
                connection.y, connection.inputToken = paddleY, token

            lScore = rScore = 0
            status = "Connecting..."
            if phase == "waiting":
                status = "Waiting for opponent..."
            elif side in paddles.bySide:
                ball.topleft = state["ball"]
                lScore, rScore = state["score"]["left"], state["score"]["right"]
                if state["points"] > lastPoints:
                    pointSound.play()
                if state["bounces"] > lastBounces:
                    bounceSound.play()
                lastPoints, lastBounces = state["points"], state["bounces"]
                status = ""
            if error:
                status = "Disconnected - close window to rejoin"

            screen.fill((0, 0, 0))
            for rect in centerLine + [topWall, bottomWall]:
                pygame.draw.rect(screen, WHITE, rect)
            paddles.draw(screen, WHITE)
            updateScore(lScore, rScore, screen, WHITE, scoreFont)
            if side in paddles.bySide:
                for playerSide, x in (("left", screenWidth // 4), ("right", 3 * screenWidth // 4)):
                    label = state["players"][playerSide]["username"]
                    surface = nameFont.render(label, False, WHITE, (0, 0, 0))
                    screen.blit(surface, surface.get_rect(center=(x, 88)))
            if finished:
                won = state["winner"] == side
                centered("You win!" if won else "Opponent wins!", winFont, screenHeight // 2 - 25)
                with connection.lock:
                    clicked = connection.rematch == token
                ready = state["you_ready"] or clicked
                pygame.draw.rect(screen, (65, 85, 95) if ready or error else (30, 125, 95),
                                 button, border_radius=6)
                label = statusFont.render("Ready!" if ready else "Play Again", False, WHITE)
                screen.blit(label, label.get_rect(center=button.center))
                displayState = dict(state, you_ready=ready)
                centered(rematchStatus(displayState), statusFont, button.bottom + 26)
            elif phase == "playing":
                pygame.draw.rect(screen, WHITE, ball)
            if status:
                centered(status, statusFont, screenHeight - 35)
            pygame.display.update()
            clock.tick(60)
    finally:
        connection.close()
        pygame.quit()


def joinServer(ip: str, port: str, username: str, initials: str, password: str,
               errorLabel: tk.Label, app: tk.Tk) -> None:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    stream = None
    try:
        client.connect((ip.strip(), int(port)))
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        stream = client.makefile("rb")
        greeting = receiveMessage(client)
        if greeting.get("type") != "challenge" or not isinstance(greeting.get("nonce"), str):
            raise ValueError("Invalid server greeting")
        sendMessage(client, {"type": "join", "username": username.strip(),
                             "initials": initials.strip(), "password": password,
                             "nonce": greeting["nonce"]})
        hello = receiveMessage(client)
        if hello.get("type") == "error":
            raise ValueError(hello["message"])
        if hello.get("type") != "hello":
            raise ValueError("Invalid server greeting")
    except (OSError, ValueError, EOFError, OverflowError) as error:
        if stream is not None:
            stream.close()
        client.close()
        errorLabel.config(text=str(error))
        return

    app.withdraw()
    try:
        playGame(hello["width"], hello["height"], hello["username"], client, stream)
    finally:
        stream.close()
        client.close()
        app.destroy()


def startScreen() -> None:
    app = tk.Tk()
    app.title("Join Pong")
    image = tk.PhotoImage(file=str(ASSETS / "images/logo.png"))
    tk.Label(app, image=image).grid(column=0, row=0, columnspan=2)
    entries = {}
    for row, (label, default) in enumerate(
            (("Server IP", "127.0.0.1"), ("Server Port", "65432"),
             ("Username", ""), ("Initials", ""), ("Password", "")), 1):
        tk.Label(app, text=label + ":").grid(column=0, row=row, sticky="W", padx=8, pady=4)
        entry = tk.Entry(app, show="*" if label == "Password" else "")
        entry.insert(0, default)
        entry.grid(column=1, row=row, padx=8)
        entries[label] = entry
    errorLabel = tk.Label(app, text="", wraplength=400, fg="red")
    errorLabel.grid(column=0, row=7, columnspan=2, padx=8, pady=8)
    tk.Button(app, text="Join", command=lambda: joinServer(
        entries["Server IP"].get(), entries["Server Port"].get(),
        entries["Username"].get(), entries["Initials"].get(),
        entries["Password"].get(), errorLabel, app)
    ).grid(column=0, row=6, columnspan=2, pady=8)
    app.mainloop()


if __name__ == "__main__":
    startScreen()

