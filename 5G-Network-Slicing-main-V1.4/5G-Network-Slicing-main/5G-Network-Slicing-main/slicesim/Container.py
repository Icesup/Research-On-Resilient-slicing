class Container:
    def __init__(self, init: float, capacity: float):
        """
        Initialize a container with a given initial level and capacity.
        """
        self.capacity = capacity
        self.level = init
    
    def get(self, amount: float) -> bool:
        """
        Attempt to remove 'amount' from the container. Return True if successful.
        """
        if amount <= self.level:
            self.level -= amount
            return True
        else:
            return False

    def put(self, amount: float) -> bool:
        """
        Attempt to add 'amount' to the container. Return True if successful.
        """
        if amount + self.level <= self.capacity:
            self.level += amount
            return True
        else:
            return False

    def __str__(self) -> str:
        return f'Container(level={self.level}, capacity={self.capacity})'
