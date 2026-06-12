# Planning Report: v3 Dashboard Design Upgrade


## Execution Stats
- Duration: ~75m
- Sub-agents spawned: 34
- Decisions grilled: 135
- Hardening passes: 7
- Spec size: 73937 chars
- Plan size: 35007 chars

## Convergence

| Pass 1 | M=13 G=3 | NOT CONVERGED |
| Pass 2 | M=13 G=2 | NOT CONVERGED |
| Pass 3 | M=13 G=0 | NOT CONVERGED |
| Pass 4 | M=12 G=3 | NOT CONVERGED |
| Pass 5 | M=10 G=3 | NOT CONVERGED |
| Pass 6 | M=10 G=0 | NOT CONVERGED |
| Pass 7 | M=10 G=3 | NOT CONVERGED |

## Decisions (135 total)

1. [high] What new React component is needed for the Search page maste
2. [high] What new sub-components are needed for contextual payload re
3. [high] What component renders the full item detail in the right pan
4. [high] What component renders individual search result rows?
5. [high] Do we need a new StateDot component for item state visualiza
6. [medium] What new API endpoint is needed for full-text search with ri
7. [high] What new database fields are needed on items table for searc
8. [high] What new TypeScript types are needed for search page?
9. [medium] What new TanStack Query hooks are needed?
10. [high] What server-side API routes are needed for item actions (sno
11. [high] How is client-side filtering implemented for kind and text s
12. [medium] Can we reuse FunnelStage component from filters page (branch
13. [high] How is the search page integrated into the app routing?
14. [high] How are action confirmations (done, snooze, archive) communi
15. [high] What empty/loading/error states are needed?
16. [medium] What accessibility considerations are needed for master/deta
17. [medium] Are there performance concerns with rich search results?
18. [medium] What is the default state when /search loads with no query?
19. [high] How is the result count displayed?
20. [medium] How is the LLM summary ('Why this matters to you') generated