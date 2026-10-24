# Human-Readable Code Policy

## 1. Primary Objective

Write code that is straightforward for another developer to understand, debug, modify, and maintain.

Prioritize:

1. Correctness and security
2. Readability and maintainability
3. Consistency with the existing project
4. Appropriate performance
5. Conciseness

Do not optimize for fewer lines of code, cleverness, novelty, or architectural sophistication.

When two solutions are similarly correct and reliable, choose the simpler one.

## 2. Inspect Before Implementing

Before changing code:

* Read the relevant source files and their callers.
* Inspect nearby implementations for established patterns.
* Check existing dependencies, utilities, abstractions, and tests.
* Understand the relevant data flow and error-handling conventions.
* Identify the smallest reasonable change that satisfies the request.

Do not invent a new architecture without first understanding the existing one.

## 3. Simplicity by Default

Prefer:

* Straightforward control flow.
* Descriptive names.
* Small, focused functions.
* Explicit conditions and return values.
* Standard, familiar APIs.
* Existing project utilities.
* Direct data transformations that are easy to follow.
* A small number of meaningful abstractions.

Avoid by default:

* Unnecessary classes and interfaces.
* Generic frameworks for one-off operations.
* Excessive helper functions.
* Deeply nested abstractions.
* Unnecessary factories, registries, adapters, and wrappers.
* Metaprogramming or reflection when ordinary code works.
* Dense comprehensions, chained expressions, and clever one-liners that reduce clarity.
* Premature optimization.
* Dependencies introduced for trivial functionality.
* Defensive code for impossible or irrelevant scenarios.

These are preferences, not absolute bans. Use a more advanced technique when the problem genuinely benefits from it.

## 4. The Justification Test

Before introducing a non-obvious technique or a new abstraction, ask:

1. Does the requirement actually need this?
2. Is there a simpler conventional solution?
3. Does the added complexity provide a concrete benefit?
4. Will another developer understand and maintain it easily?
5. Is this consistent with the existing codebase?

If the simpler solution satisfies the requirements, use it.

If additional complexity is justified by security, correctness, performance, concurrency, or a real architectural constraint, use it and briefly explain why.

Do not add complexity merely for hypothetical future requirements.

## 5. Match the Project

* Follow existing naming, formatting, typing, testing, and error-handling conventions.
* Prefer established project dependencies over introducing new ones.
* Reuse existing abstractions when they genuinely simplify the implementation.
* Do not replace working patterns with a new architectural style without a concrete reason.
* Do not rewrite unrelated files.
* Do not create parallel implementations of functionality that already exists.
* Keep changes limited to the requested feature and necessary supporting changes.

Existing code is evidence of project conventions, but not an excuse to reproduce obvious bugs, security vulnerabilities, or clearly harmful patterns.

## 6. Language and Framework Conventions

Use familiar, idiomatic patterns for the language and framework being used.

* Python: prefer clear functions, ordinary control flow, standard-library solutions, and appropriate type hints.
* JavaScript and TypeScript: prefer clear functions, explicit data flow, and established project conventions.
* React and Next.js: follow existing component boundaries, rendering patterns, and state-management conventions.
* Java and C++: use familiar language constructs and avoid unnecessary abstractions or template complexity.
* SQL: write understandable queries and use advanced query features when they meaningfully improve correctness, performance, or clarity.
* Other languages: follow the language's established conventions and the project's existing patterns.

These are defaults, not rigid language-specific restrictions.

## 7. Functions and Abstractions

* Give each function one clear responsibility.
* Extract a helper when it improves clarity, reuse, or testability.
* Do not extract every few lines into a separate function without a benefit.
* Use a class when it represents meaningful state, behavior, or a useful abstraction.
* Do not create a class merely to hold one unrelated function.
* Avoid overly generic parameter lists and unnecessary configuration layers.
* Keep interfaces and extension points proportional to actual requirements.

## 8. Comments and Documentation

* Write code that explains itself through clear naming and structure.
* Comment non-obvious reasoning, constraints, trade-offs, and important edge cases.
* Avoid comments that merely repeat the code.
* Document public APIs and complex behavior when appropriate.
* Do not use comments as a substitute for simplifying confusing code.

## 9. Correctness and Safety

Simplicity must never come at the expense of:

* Correct behavior and required edge cases.
* Input validation at appropriate boundaries.
* Authentication, authorization, and data protection.
* Correct resource management.
* Meaningful error handling.
* Required performance and scalability constraints.

Do not silently ignore exceptions or hide failures.

## 10. Mandatory Final Review

Before declaring the task complete:

1. Review the entire diff.
2. Identify abstractions, dependencies, helpers, and code paths that are not necessary.
3. Replace unnecessarily clever code with clearer conventional code where practical.
4. Verify consistency with neighboring implementations.
5. Run the relevant existing tests, formatter, linter, or type checker when available.
6. Report checks that were not run or failed.

Do not make unrelated refactors during cleanup.

## 11. Completion Summary

At the end of the task, summarize:

* What changed.
* Why the chosen approach fits the existing project.
* Any important trade-offs or non-obvious techniques.
* Which verification commands were run and their results.

Keep the explanation concise and factual.

## Final Decision Rule

The preferred implementation is the simplest conventional solution that correctly satisfies the actual requirements and fits the existing architecture.

Write code for the next developer who must maintain it, not for the purpose of demonstrating how sophisticated the implementation can be.
