import math


class Coverage:
    def __init__(self, center: tuple, radius: float):
        """
        Initialize coverage with a center and radius.
        """
        self.center = center
        self.radius = radius

    def _get_gaussian_distance(self, p: tuple) -> float:
        """
        Calculate the Euclidean distance from point p to the center.
        """
        return math.sqrt(sum((i-j)**2 for i,j in zip(p, self.center)))

    def is_in_coverage(self, x: float, y: float) -> bool:
        """
        Check if the point (x, y) is within the coverage radius.
        """
        return self._get_gaussian_distance((x,y)) <= self.radius

    def __str__(self) -> str:
        x, y = self.center
        return f'[c=({x:<4}, {y:>4}), r={self.radius:>4}]'