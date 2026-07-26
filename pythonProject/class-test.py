import time
class User:
    def __init__(self, name, family):
        self.name = name  # self — это объект
        self.family = family

    def greet(self):
        print(f"Hello, {self.name} {self.family}")

u = User("Ivan", "Хуевич")
u.greet()  # Hello, Ivan
