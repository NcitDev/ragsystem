import os  # noqa: F401 - import chunk is part of the cross-runtime golden fixture


class Greeter:
    def hello(self, name: str) -> str:
        return f"hello {name}"


def build_message(name: str) -> str:
    return Greeter().hello(name)
