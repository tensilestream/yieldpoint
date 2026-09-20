# which part of the request breaks tool calling

replayed from `opencode_request.json`, one change at a time

| variant | structured tool calls | first reply |
|---|---|---|
| baseline (unchanged) | 0/4 | `text, not a tool call` |
| no $schema in parameters | 0/4 | `text, not a tool call` |
| tool descriptions, first line only | 4/4 | `edit` |
| no system prompt | 0/4 | `text, not a tool call` |
| first line + no system prompt | 4/4 | `edit` |
