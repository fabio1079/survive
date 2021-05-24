import random
import math
from typing import Callable, List
from abc import ABC, abstractmethod
import enum
import pyxel
from easymunk import Vec2d, Arbiter, CircleBody, Space, march_string, ShapeFilter
from easymunk import pyxel as phys

MAX_WIDTH = 1000
WIDTH, HEIGHT = 256, 196
INITIAL_ENEMIES = 5
SCENARIO = """
|
|
|
|
|                                              =
|                                              ==
|                     ===                      ===
|                                              ====
|            ===   ===             ===         =====
|                                  ===
|=====    ===                      ===
|X
|X
"""


class ColType(enum.IntEnum):
    PLAYER = 1
    ENEMY = 2
    TARGET = 3
    BULLET = 4


class GameState(enum.IntEnum):
    RUNNING = 1
    GAME_OVER = 2
    HAS_WON = 3


class GameObject(ABC):
    @abstractmethod
    def update(self):
        ...

    @abstractmethod
    def draw(self):
        ...

    @abstractmethod
    def register(self, space: Space, message: Callable[[str, "GameObject"], None]):
        ...


class Bullet(GameObject, CircleBody):
    COLOR = pyxel.COLOR_RED
    life_time = 150

    def __init__(self, x, y, target_x, target_y, del_bullet):
        super().__init__(
            radius=2,
            position=(x, y),
            elasticity=0.0,
            color=self.COLOR,
            collision_type=ColType.BULLET,
        )
        self.del_bullet = del_bullet
        angle = math.atan2(target_y - y, target_x - x)  # angle to target in radians

        self.dx = math.cos(angle)
        self.dy = math.sin(angle)

        self.velocity = Vec2d(self.dx, self.dy)

    def update(self):
        dp = self.position + self.velocity
        self.position = dp

        self.life_time -= 1

        if self.life_time < 0:
            self.del_bullet(self)

    def draw(self, camera=pyxel):
        x, y = self.position
        camera.circ(x, y, self.radius, self.COLOR)

    def register(self, space, message):
        pass


class Player(GameObject, CircleBody):
    SPEED = 90
    JUMP_SPEED = 120
    COLOR = pyxel.COLOR_RED
    camera: pyxel = None

    def __init__(self, camera: pyxel, x, y):
        super().__init__(
            radius=4,
            position=(x, y),
            elasticity=0.0,
            collision_type=ColType.PLAYER,
        )
        self.camera = camera
        self.can_jump = False

    def update(self):
        v = self.velocity
        mass = self.mass
        # F = mass * 200
        self.force += Vec2d(0, -mass * 200)

        if pyxel.btn(pyxel.KEY_A):
            if self.can_jump:
                v = Vec2d(-self.SPEED, v.y)
            else:
                v = Vec2d(-self.SPEED / 2, v.y)
        elif pyxel.btn(pyxel.KEY_D):
            if self.can_jump:
                v = Vec2d(+self.SPEED, v.y)
            else:
                v = Vec2d(+self.SPEED / 2, v.y)
        else:
            r = 0.5 if self.can_jump else 1.0
            v = Vec2d(v.x * r, v.y)

        if self.can_jump and pyxel.btnp(pyxel.KEY_W):
            v = Vec2d(v.x, self.JUMP_SPEED)

        self.velocity = v

    def draw(self, camera=pyxel):
        x, y, _right, _top = self.bb
        sign = 1 if self.velocity.x >= 0 else -1

        idx = int(self.position.x / 2) % 4
        u = 8 * idx
        camera.blt(x, y, 0, u, 0, sign * 8, 8, pyxel.COLOR_YELLOW)

    def register(self, space, message):
        space.add(self)

        @space.post_solve_collision(ColType.PLAYER, ...)
        def _col_start(arb: Arbiter):
            n = arb.normal_from(self)
            self.can_jump = n.y <= -0.5

        @space.separate_collision(ColType.PLAYER, ...)
        def _col_end(arb: Arbiter):
            self.can_jump = False


class Enemy(GameObject, CircleBody):
    RADIUS = 16
    SPEED = 90
    COLOR = pyxel.COLOR_CYAN
    lives = 4

    @staticmethod
    def random(xmin, xmax, ymin, ymax):
        vx = random.uniform(-Enemy.SPEED / 2, Enemy.SPEED / 2)
        vy = random.uniform(0, Enemy.SPEED / 2)
        return Enemy(
            x=random.uniform(xmin + Enemy.RADIUS, xmax - Enemy.RADIUS),
            y=random.uniform(ymin + Enemy.RADIUS, ymax - Enemy.RADIUS),
            velocity=(vx, vy),
            angular_velocity=random.uniform(-360, 360),
        )

    def __init__(self, x, y, **kwargs):
        super().__init__(
            radius=random.randint(4, 24),
            position=(x, y),
            friction=0.0,
            elasticity=1.0,
            color=self.COLOR,
            collision_type=ColType.ENEMY,
            **kwargs,
        )

    @property
    def get_color(self):
        if self.lives == 4:
            return pyxel.COLOR_CYAN
        elif self.lives == 3:
            return pyxel.COLOR_YELLOW
        elif self.lives == 2:
            return pyxel.COLOR_PINK
        elif self.lives == 1:
            return pyxel.COLOR_RED
        else:
            return pyxel.COLOR_BROWN

    def update(self):
        ...

    def draw(self, camera=pyxel):
        x, y = self.position
        camera.circb(x, y, self.radius, self.get_color)

    def register(self, space, message):
        space.add(self)

        @space.begin_collision(ColType.PLAYER, ColType.ENEMY)
        def begin(arb: Arbiter):
            shape_a, shape_b = arb.shapes
            if shape_a.collision_type == ColType.PLAYER:
                player, enemy = shape_a, shape_b
            else:
                player, enemy = shape_b, shape_b

            n = arb.normal_from(player)
            if n.y < 0.25:
                space.remove(enemy)
            else:
                message("hit_player", sender=self)

            return True


class DeathParticles(GameObject):
    MAX_DURATION = 30  # each particle duration
    MAX_GENERATED = 100  # total number of generated particles on death animation

    def __init__(self, space, remove_me):
        self.particles = []
        self.space = space
        self.remove_me = remove_me
        self.duration = self.MAX_DURATION
        self.generated = 0
        self.color_scale = self.MAX_DURATION / 6

    def update(self):
        for p in self.particles.copy():
            p.velocity = p.velocity.rotated(random.uniform(-5, 5))
            p.duration -= 1

            if p.duration <= 0:
                self.particles.remove(p)
                self.space.remove(p)

        if len(self.particles) == 0:
            self.remove_me(self)

    def draw(self, camera=pyxel):
        for p in self.particles:
            x, y = p.position
            if random.random() < 0.15:
                camera.rect(x, y, 2, 2, self.get_color(p.duration))
            else:
                camera.pset(x, y, self.get_color(p.duration))

    def register(self, space, message):
        pass

    @property
    def keep_generating(self):
        return self.generated < self.MAX_GENERATED

    def generate_particles(self, position, batch_size=100):
        if not self.keep_generating:
            return  # stop generating more particles

        for _ in range(batch_size):
            velocity = Vec2d(
                random.uniform(50, 90) * math.sin(random.randint(10, 160)),
                random.uniform(50, 90) * math.sin(random.randint(10, 160)),
            )

            self.emmit(position=position, velocity=velocity)

    def emmit(self, position, velocity):
        if not self.keep_generating:
            return  # stop generating more particles

        self.generated += 1

        p = self.space.create_circle(
            radius=1,
            mass=0.1,
            moment=float("inf"),
            position=position,
            velocity=velocity,
            filter=ShapeFilter(group=1),
        )

        p.duration = self.duration - random.expovariate(1 / 10)
        p.velocity_func = self.update_velocity
        self.particles.append(p)

    def update_velocity(self, body, gravity, damping, dt):
        body.update_velocity(body, -gravity / 2, 0.99, dt)

    def get_color(self, t: int):
        if t > self.color_scale * 5:
            return pyxel.COLOR_WHITE
        elif t > self.color_scale * 4:
            return pyxel.COLOR_YELLOW
        elif t > self.color_scale * 3:
            return pyxel.COLOR_RED
        elif t > self.color_scale * 2:
            return pyxel.COLOR_ORANGE
        elif t > self.color_scale * 1:
            return pyxel.COLOR_PURPLE
        else:
            return pyxel.COLOR_GRAY


class Game:
    CAMERA_TOL = Vec2d(WIDTH / 2 - 64, HEIGHT / 2 - 48)
    enemies: List[Enemy] = []
    player: Player = None
    bullets: List[Bullet] = []
    MAX_BULLETS = 10
    particles: List[DeathParticles] = []

    def __init__(self, scenario=SCENARIO):
        self.camera = phys.Camera(flip_y=True)
        self.space = phys.space(
            gravity=(0, -25),
            wireframe=True,
            camera=self.camera,
            elasticity=1.0,
        )

        # Inicializa o jogo
        self.state = GameState.RUNNING
        pyxel.load("assets.pyxres")

        # Cria jogador
        self.player = Player(self.camera, 50, 50)
        self.player.register(self.space, self.message)

        # Cria chão
        self.ground = phys.rect(0, 0, MAX_WIDTH, 48, body_type="static")

        # Cria cenário
        for line in march_string(
            scenario, "=", scale=8.0, translate=Vec2d(0.0, 48), flip_y=True
        ):
            line = [Vec2d(2 * x, y) for (x, y) in line]
            phys.poly(line, body_type="static", color=pyxel.COLOR_PEACH)

        # Cria margens
        phys.margin(0, 0, MAX_WIDTH, HEIGHT)

        # Cria inimigos
        for _ in range(INITIAL_ENEMIES):
            enemy = Enemy.random(0, MAX_WIDTH, HEIGHT / 2, HEIGHT)
            enemy.register(self.space, self.message)
            self.enemies.append(enemy)

    def message(self, msg, sender):
        fn = getattr(self, f"handle_{msg}", None)
        if fn is None:
            print(f'Mensagem desconhecida: "{msg} ({sender})')
        else:
            fn(sender)

    def handle_hit_player(self, sender):
        self.state = GameState.GAME_OVER

    def draw(self):
        pyxel.cls(0)
        for body in self.space.bodies:
            if isinstance(body, (Player, Enemy)):
                body.draw(self.camera)
            else:
                self.camera.draw(body)

        for b in self.bullets:
            b.draw(self.camera)

        for p in self.particles:
            p.draw(self.camera)

        msg = ""
        if self.state is GameState.GAME_OVER:
            msg = "GAME OVER"
        elif self.state is GameState.HAS_WON:
            msg = "PARABENS!"

        if msg:
            x = (WIDTH - len(msg) * pyxel.FONT_WIDTH) / 2
            pyxel.text(round(x), HEIGHT // 2, msg, pyxel.COLOR_YELLOW)

    def update(self):
        self.space.step(1 / 30, 2)

        if self.state is not GameState.GAME_OVER:
            self.player.update()

        self.camera.follow(self.player.position, tol=self.CAMERA_TOL)
        # self.camera.follow(self.player.position)

        for b in self.bullets:
            b.update()
            self.verify_bullet_hit_enemies(b)

        for p in self.particles:
            p.update()

        if self.state == GameState.RUNNING and pyxel.btnp(pyxel.MOUSE_LEFT_BUTTON):
            self.shoot_bullet()

        if len(self.enemies) == 0:
            self.state = GameState.HAS_WON

    def verify_bullet_hit_enemies(self, b: Bullet):
        (bx, by) = b.position

        for e in self.enemies:
            (ex, ey) = e.position
            dx = (bx - ex) ** 2
            dy = (by - ey) ** 2

            if dx + dy <= e.radius ** 2:
                self.del_bullet(b)
                e.lives -= 1

                if e.lives <= 0:
                    self.del_enemy(e)

    def shoot_bullet(self):
        if len(self.bullets) > self.MAX_BULLETS:
            return

        (px, py) = self.player.position
        (mx, my) = self.correct_mouse_distance(px, self.camera)

        b = Bullet(px, py, mx, my, self.del_bullet)
        b.register(self.space, self.message)
        self.bullets.append(b)

    def del_bullet(self, b: Bullet):
        self.bullets.remove(b)

    def del_enemy(self, e: Enemy):
        self.enemies.remove(e)
        self.space.remove(e)

        death = DeathParticles(self.space, remove_me=self.remove_death_particle)
        enemy_position = e.local_to_world((random.uniform(-2, 2), -3))
        death.generate_particles(enemy_position)
        self.particles.append(death)

    def remove_death_particle(self, p: DeathParticles):
        self.particles.remove(p)

    def correct_mouse_distance(self, px, camera: phys.Camera):
        mx = camera.mouse_x
        my = camera.mouse_y

        return (px + mx - (WIDTH / 2), my)


if __name__ == "__main__":
    pyxel.init(WIDTH, HEIGHT)
    pyxel.mouse(True)
    game = Game()
    pyxel.run(game.update, game.draw)
