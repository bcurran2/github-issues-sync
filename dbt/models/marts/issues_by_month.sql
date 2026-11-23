with opened as (
    select
        date_trunc(date(created_at), month) as month,
        count(*) as issues_opened
    from {{ ref('stg_github__issues') }}
    group by 1
),

closed as (
    select
        date_trunc(date(closed_at), month) as month,
        count(*) as issues_closed
    from {{ ref('stg_github__issues') }}
    where closed_at is not null
    group by 1
),

months as (
    select month from opened
    union distinct
    select month from closed
),

combined as (
    select
        months.month,
        coalesce(opened.issues_opened, 0) as issues_opened,
        coalesce(closed.issues_closed, 0) as issues_closed
    from months
    left join opened on months.month = opened.month
    left join closed on months.month = closed.month
)

select
    month,
    issues_opened,
    issues_closed,
    issues_opened - issues_closed as net_change,
    sum(issues_opened - issues_closed) over (order by month) as open_backlog
from combined
order by month