# Java Coding Conventions
- 4-space indentation, braces on the same line, one public class per file.
- Class names in PascalCase, methods and fields in camelCase, constants in UPPER_SNAKE_CASE.
- Constructor injection for dependencies; no static mutable state.
- Add a short Javadoc comment to every new public method.
- Validate inputs at service boundaries; throw IllegalArgumentException for bad input.
- Do not log account numbers or customer names.
- Keep existing method signatures stable; add new methods rather than changing old ones.
