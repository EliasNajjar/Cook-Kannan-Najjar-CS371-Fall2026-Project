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

# Author: Elias Najjar
# Purpose: Convert a message to JSON, encrypt it with Fernet, and send it.
# Pre: client is connected, message is JSON serializable,
#      and FERNET is initialized with the shared key.
# Post: The encrypted message is submitted to the socket for sending.
def sendMessage(client: socket.socket, message: dict) -> None:
    client.send(FERNET.encrypt(json.dumps(message).encode())) # encode and send fernet encrypted message to server

# Author: Elias Najjar
# Purpose: Receive a message from the server, decrypt it with Fernet, and return the decoded JSON object.
# Pre: client is connected and FERNET is initialized with the shared key.
# Post: The decrypted and loaded dict object is returned.
def receiveMessage(client: socket.socket) -> dict:
    return json.loads(FERNET.decrypt(client.recv(MAX_LEN))) # return decrypted and loaded dict object from server

ASSETS = Path(__file__).resolve().parent / "assets"

class Paddles:
    """Keep paddle setup, movement, snapshot updates and drawing together."""

    # Author: Mohandass Kannan
    # Purpose: Create the left and right paddles and initialize round tracking.
    # Pre: Pygame is available, and width and height can accommodate the court.
    # Post: Both paddles are positioned at their starting locations,
    #       height is stored, and token is None.
    def __init__(self, width: int, height: int) -> None:
        self.height = height
        # Place both padddles at the vertical center of their sides
        self.bySide = {
            "left": Paddle(pygame.Rect(10, height // 2 - 25, 10, 50)),
            "right": Paddle(pygame.Rect(width - 20, height // 2 - 25, 10, 50)),
        }
        # Track the match and round to detect when the paddles need to reset
        self.token = None

    # Author: Mohandass Kannan
    # Purpose: Update the local paddle from keyboard input and the opponent's
    #          paddle from server state.
    # Pre: Paddles are initialized, Pygame input is available, and state includes
    #      both paddle positions whenever a valid player side is assigned.
    # Post: Paddle positions and round tracking are updated. The local paddle's
    #       y-coordinate, or the default starting coordinate, is returned.
    def update(self, state: dict, connected: bool) -> int:
        side = state.get("side")
        token = (state.get("match_id"), state.get("round"))

        # Reset the position when a new match or round starts
        if token != self.token:
            for paddle in self.bySide.values():
                paddle.rect.y = self.height // 2 - 25
            if side in self.bySide:
                self.bySide[side].rect.topleft = state["paddles"][side]
            self.token = token

        # return the starting position until the server assigns a side
        if side not in self.bySide:
            return self.height // 2 - 25
        # Move only our paddle locally; the opponent comes from the server.
        keys = pygame.key.get_pressed()
        movement = int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP])
        own = self.bySide[side]

        # Move our paddle during play, keep it within the screen bounds, and update the opponent's paddle from the server.  The server is authoritative, so we don't move the opponent's paddle locally.
        if state.get("phase") == "playing" and connected:
            own.rect.y = max(10, min(self.height - 60, own.rect.y + movement * own.speed))
        for other, paddle in self.bySide.items():
            if other != side:
                paddle.rect.topleft = state["paddles"][other]

        # Provide our paddle position to the server
        return own.rect.y

    # Author: Mohandass Kannan
    # Purpose: Draw both paddles onto the supplied screen.
    # Pre: Both paddles exist, screen is a valid Pygame surface,
    #      and color is a valid Pygame color tuple.
    # Post: Both paddle rectangles are drawn onto screen.
    def draw(self, screen: pygame.Surface, color: tuple) -> None:
        for paddle in self.bySide.values():
            pygame.draw.rect(screen, color, paddle.rect)


class ServerConnection:
    """Exchange snapshots in a background thread so the UI stays responsive."""

    # Author: Mohandass Kannan and Elias Najjar
    # Purpose: Initialize connection data and prepare the network thread.
    # Pre: client is a connected socket, stream is its open binary read stream,
    #      and startY is the initial paddle y-coordinate.
    # Post: Shared data, synchronization objects, and the network thread are
    #       initialized. The thread has not started.
    def __init__(self, client: socket.socket, stream: BinaryIO, startY: int) -> None:
        self.client = client
        self.stream = stream

        # Store local input for the network to send
        self.y = startY
        self.inputToken = (None, None)

        # Store the latest server state and any rematch request, along with any error message.  These are read by the UI thread while holding the lock to avoid race conditions.
        self.state: dict | None = None
        self.rematch: tuple | None = None
        self.error = ""

        # Protect data shared between the game and the network
        self.lock = threading.Lock()

        # Signal when the network thread should stop
        self.stopped = threading.Event()

        # Prepare the network thread to start when thread.start() is called.  The thread is a daemon so it will exit when the main program exits.
        self.thread = threading.Thread(target=self.exchange, daemon=True)


    # Author: Mohandass Kannan
    # Purpose: Repeatedly send player input and receive server game states
    #          in the background.
    # Pre: Connection data and synchronization objects are initialized,
    #      and the socket is available for communication.
    # Post: The loop ends when stopped or when a handled error occurs.
    #       Received states are stored, and any handled error is recorded.
    def exchange(self) -> None:
        # Exchange messages with the server until the connection is stopped.
        try:
            while not self.stopped.is_set():
                with self.lock:
                    # The position and its round come from the same rendered frame.
                    token = self.inputToken
                    message = {"type": "update", "y": self.y,
                               "match_id": token[0], "round": token[1],
                               # Send a rematch request only for the matching round, and only if the player clicked the button.  The server will ignore rematch requests for other rounds.
                               "play_again": self.rematch is not None and self.rematch == token}

                # Send local input and receive the latest game state.

                sendMessage(self.client, message)
                state = receiveMessage(self.client)

                # Reject server errors and unexpected messages
                if state.get("type") == "error":
                    raise ValueError(state.get("message", "Server error"))
                if state.get("type") != "state":
                    raise ValueError("Expected game state from server")

                # Share the latest state with the game thread
                with self.lock:
                    self.state = state

                # Pause between every exchange to avoid overwhelming the server
                self.stopped.wait(1 / 60)
        except (OSError, ValueError, EOFError) as error:
            # Share connection errors so the game can display a message
            with self.lock:
                self.error = f"Connection lost: {error}"

    # Author: Mohandass Kannan
    # Purpose: Stop network communication and wait for the network thread to exit.
    # Pre: The network thread has started, and this method is called
    #      from another thread.
    # Post: The stop event is set, socket shutdown is attempted,
    #       and the network thread has finished.
    def close(self) -> None:
        self.stopped.set()
        try:
            # Interrupt any blocked socket reads or writes
            self.client.shutdown(socket.SHUT_RDWR)
        except OSError:
            # The scoket may already be closed, ignore the error
            pass
        # Wati for the thread to finish
        self.thread.join()


# Author: Mohandass Kannan
# Purpose: Select a rematch status message based on both players' readiness.
# Pre: state is a dictionary that may contain you_ready and opponent_ready.
# Post: A status string is returned without modifying state.
def rematchStatus(state: dict) -> str:
    if state.get("you_ready") and state.get("opponent_ready"):
        return "Starting next game..."
    if state.get("you_ready"):
        return "Waiting for opponent..."
    if state.get("opponent_ready"):
        return "Opponent wants to play again."
    return "Both players must click to restart."

# Author: Mohandass Kannan, Hayden Cook, and Elias Najjar
# Purpose: Handle player input and display gameplay using server updates.
# Pre: The server has accepted the player, client and stream are open,
#      screen dimensions are valid, and required assets are available.
# Post: The network thread is stopped and Pygame resources are released.
def playGame(screenWidth: int, screenHeight: int, username: str,
             client: socket.socket, stream: BinaryIO) -> None:

    # Initialize Pygame and configure audio
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.init()
    WHITE = (255, 255, 255)
    clock = pygame.time.Clock()

    # Load fonts and sounds from the assets directory

    scoreFont = pygame.font.Font(str(ASSETS / "fonts/pong-score.ttf"), 32)
    winFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 40)
    statusFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 24)
    nameFont = pygame.font.Font(str(ASSETS / "fonts/visitor.ttf"), 20)
    pointSound = pygame.mixer.Sound(str(ASSETS / "sounds/point.wav"))
    bounceSound = pygame.mixer.Sound(str(ASSETS / "sounds/bounce.wav"))

    # Create the game window and graphics

    screen = pygame.display.set_mode((screenWidth, screenHeight))
    pygame.display.set_caption(f"Pong - {username}")
    topWall = pygame.Rect(-10, 0, screenWidth + 20, 10)
    bottomWall = pygame.Rect(-10, screenHeight - 10, screenWidth + 20, 10)
    centerLine = [pygame.Rect(screenWidth // 2 - 5, y, 5, 5)
                  for y in range(0, screenHeight, 10)]
    paddles = Paddles(screenWidth, screenHeight)
    ball = pygame.Rect(screenWidth // 2, screenHeight // 2, 5, 5)
    button = pygame.Rect(screenWidth // 2 - 110, screenHeight // 2 + 45, 220, 46)

    # Run network communication in a background thread

    connection = ServerConnection(client, stream, screenHeight // 2 - 25)
    connection.thread.start()

    # Track the current round and previously received sound-events to avoid replaying them multiple times

    lastToken = None
    lastPoints = lastBounces = 0
    running = True

    # Author: Mohandass Kannan
    # Purpose: Draw text horizontally centered at the specified vertical position.
    # Pre: screen is initialized, font is loaded, and text is a string.
    # Post: The rendered text is drawn onto screen, ready for display.
    def centered(text, font, y, color=WHITE):
        surface = font.render(text, False, color, (0, 0, 0))
        screen.blit(surface, surface.get_rect(center=(screenWidth // 2, y)))

    try:
        while running:
            # Read shared network data while holding the thread lock to avoid race conditions.  The lock is held only briefly, so the UI can remain responsive.
            with connection.lock:
                state = connection.state
                error = connection.error
            state = state or {}
            phase = state.get("phase", "connecting")
            side = state.get("side")
            token = (state.get("match_id"), state.get("round"))
            finished = phase == "finished"

            # Handle closing the window and clicking the rematch button
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                      and button.collidepoint(event.pos) and finished and not error):
                    with connection.lock:
                        connection.rematch = token
            if not running:
                break

            # Reset sound tracking when the match or round changes
            if token != lastToken:
                lastPoints = lastBounces = 0
                lastToken = token

            # Update the paddle and share position with server
            paddleY = paddles.update(state, connected=not error)
            with connection.lock:
                connection.y, connection.inputToken = paddleY, token

            lScore = rScore = 0
            status = "Connecting..."
            if phase == "waiting":
                status = "Waiting for opponent..."
            elif side in paddles.bySide:
                # Use server's ball position and score
                ball.topleft = state["ball"]
                lScore, rScore = state["score"]["left"], state["score"]["right"]

                # Play sounds only when the server reports a new point or bounce, to avoid replaying them multiple times
                if state["points"] > lastPoints:
                    pointSound.play()
                if state["bounces"] > lastBounces:
                    bounceSound.play()
                lastPoints, lastBounces = state["points"], state["bounces"]
                status = ""
            if error:
                status = "Disconnected - close window to rejoin"

            # Clear the previous frames and draw court, paddles and scores

            screen.fill((0, 0, 0))
            for rect in centerLine + [topWall, bottomWall]:
                pygame.draw.rect(screen, WHITE, rect)
            paddles.draw(screen, WHITE)
            updateScore(lScore, rScore, screen, WHITE, scoreFont)

            # Display each player's username above their side of the court
            if side in paddles.bySide:
                for playerSide, x in (("left", screenWidth // 4), ("right", 3 * screenWidth // 4)):
                    label = state["players"][playerSide]["username"]
                    surface = nameFont.render(label, False, WHITE, (0, 0, 0))
                    screen.blit(surface, surface.get_rect(center=(x, 88)))

            if finished:
                # Show the result and rematch controls when the game is finished.
                won = state["winner"] == side
                centered("You win!" if won else "Opponent wins!", winFont, screenHeight // 2 - 25)
                with connection.lock:
                    clicked = connection.rematch == token

                # Show readiness immediately if the player clicked, or if the server reports that the player is ready.  The button is green when the player can click to ready up, and gray when the player is already ready or there is a connection error.
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

            # Display frame and limit to 60 FPS.
            pygame.display.update()
            clock.tick(60)
    finally:
        # Close the network connection and release the Pygame resources.
        connection.close()
        pygame.quit()


# Author: Elias Najjar
# Purpose: Connect to the server, submit player information, and start the game.
# Pre: errorLabel and app are valid Tkinter objects, and connection information
#      and player details are provided as strings.
# Post: If joining fails, an error is displayed and the connection is closed.
#       Otherwise, gameplay runs, then connection resources and app are closed.
def joinServer(ip: str, port: str, username: str, initials: str, password: str,
               errorLabel: tk.Label, app: tk.Tk) -> None:
    
    # Create a TCP conection with a five-second timeout

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    stream = None
    try:
        client.connect((ip.strip(), int(port)))

        # Send small messages promptly, need gameplay to be responsive

        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        stream = client.makefile("rb")

        # Verify that the server sent a valid challenge message, then send a join request with the username, initials, password and the nonce from the challenge. 

        greeting = receiveMessage(client)
        if greeting.get("type") != "challenge" or not isinstance(greeting.get("nonce"), str):
            raise ValueError("Invalid server greeting")
        
        sendMessage(client, {"type": "join", "username": username.strip(),
                             "initials": initials.strip(), "password": password,
                             "nonce": greeting["nonce"]})

        # Check if the server accepted the player
        
        hello = receiveMessage(client)
        if hello.get("type") == "error":
            raise ValueError(hello["message"])
        if hello.get("type") != "hello":
            raise ValueError("Invalid server greeting")
        
    except (OSError, ValueError, EOFError, OverflowError) as error:
        # Clean up any failed connections and display the error message to the user
        if stream is not None:
            stream.close()
        client.close()
        errorLabel.config(text=str(error))
        return

    # Hide the login window and start the game loop with the server-provided screen dimensions and username.  The game loop will handle closing the window when the game is over.
    app.withdraw()
    try:
        playGame(hello["width"], hello["height"], hello["username"], client, stream)
    finally:
        stream.close()
        client.close()
        app.destroy()


# Author: Mohandass Kannan, Elias Najjar, and Hayden Cook
# Purpose: Display the join screen and let the player enter connection
#          information and submit a request to join the server.
# Pre: Tkinter is available, the logo image exists at the specified asset
#      path, and joinServer is defined.
# Post: The Tkinter event loop has ended. Join requests made through the
#       form are handled by joinServer.
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

