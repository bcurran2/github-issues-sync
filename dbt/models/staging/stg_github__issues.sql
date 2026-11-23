select
    id as issue_id,
    number as issue_number,
    state,
    title,
    author,
    comments as comment_count,
    created_at,
    updated_at,
    closed_at,
    html_url,
    state = 'closed' as is_closed
from {{ source('github', 'issues') }}