class Distributor:
    def __init__(self, name: str, distribution, *dist_params, divide_scale: float = 1):
        """
        Initialize a distribution generator for usage or movement.
        """
        self.name = name
        self.distribution = distribution
        self.dist_params = dist_params
        self.divide_scale = divide_scale

    def generate(self) -> float:
        """
        Generate a value from the distribution.
        """
        return self.distribution(*self.dist_params)

    def generate_scaled(self) -> float:
        """
        Generate a value from the distribution and scale it.
        """
        return self.distribution(*self.dist_params) / self.divide_scale

    def generate_movement(self) -> tuple:
        """
        Generate a movement tuple (x, y) from the distribution.
        """
        x = self.distribution(*self.dist_params) / self.divide_scale
        y = self.distribution(*self.dist_params) / self.divide_scale
        return x, y

    def __str__(self) -> str:
        dist_name = getattr(self.distribution, '__name__', str(self.distribution))
        return f'[{self.name}: {dist_name}: {self.dist_params}]'