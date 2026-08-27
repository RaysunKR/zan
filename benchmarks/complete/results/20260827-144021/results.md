| Test | zan | flask | zan_multi | zan vs flask |
| --- | ---: | ---: | ---: | ---: |
| plaintext | 20134 | 41219 | 64702 | 0.5x |
| json | 17547 | 39655 | 50215 | 0.4x |
| db | 596 | 6309 | 866 | 0.1x |
| queries | 225 | 1619 | 454 | 0.1x |
| updates | 223 | 2494 | 465 | 0.1x |
| fortunes | 586 | 5916 | 847 | 0.1x |

### Latency (median round)

| Test | zan | flask | zan_multi |
| --- | --- | --- | --- |
| plaintext | 122.21ms | 391.41ms | 21.49ms |
| json | 19.42ms | 44.44ms | 5.40ms |
| db | 235.98ms | 104.05ms | 337.82ms |
| queries | 951.78ms | 185.16ms | 545.92ms |
| updates | 913.99ms | 133.29ms | 431.96ms |
| fortunes | 227.72ms | 110.19ms | 343.10ms |

### Errors (median round)

| Test | zan (connect/read/write/timeout) | flask (connect/read/write/timeout) | zan_multi (connect/read/write/timeout) |
| --- | --- | --- | --- |
| plaintext | 0/0/0/0 | 0/0/0/135 | 0/0/0/0 |
| json | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| db | 0/0/0/1 | 0/0/0/0 | 0/0/0/8 |
| queries | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| updates | 0/0/0/98 | 0/0/0/179 | 0/0/0/87 |
| fortunes | 0/0/0/0 | 0/0/0/0 | 0/0/0/19 |
