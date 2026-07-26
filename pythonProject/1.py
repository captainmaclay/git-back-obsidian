class Dog:

    def __init__(self, name, color, breed, age=0):
        self.__name = name
        self.__color = color
        self.__breed = breed
        self.__age = age
        self.__check_color()
    def __check_color(self):
        if self.__breed == "wss":
            self.__color = "white"
    def get_info(self):
        return f"{self.__name} {self.__color} {self.__breed}"
    def add_year(self):
        self.__age += 1
    def bark_age(self):
        print("bark!"*self.__age)

d = Dog ("zephyrka", "white", "wss", 2)
print(d._Dog__name)
d._Dog__name = "Zephyrka"
d._Dog__check_color()
d.bark_age()