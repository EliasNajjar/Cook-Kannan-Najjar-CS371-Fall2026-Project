# You don't need to edit this file at all unless you really want to
import pygame

# This draws the score to the screen
def updateScore(lScore:int, rScore:int, screen:pygame.surface.Surface, color, scoreFont:pygame.font.Font) -> pygame.Rect:
    textSurface = scoreFont.render(f"{lScore}   {rScore}", False, color)
    textRect = textSurface.get_rect()
    screenWidth = screen.get_width()
    textRect.center = ((screenWidth/2)+5, 50)
    return screen.blit(textSurface, textRect)

class Paddle:
    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self.moving = ""
        self.speed = 5
