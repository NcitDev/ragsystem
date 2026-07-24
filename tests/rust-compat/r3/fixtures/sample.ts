import { readFileSync } from "node:fs";

export class Greeter {
  hello(name: string): string {
    return `hello ${name}`;
  }
}

export function buildMessage(name: string): string {
  return new Greeter().hello(name);
}
