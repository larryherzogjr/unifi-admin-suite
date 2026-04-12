# UniFi Admin Suite

A four-service physical security management platform for UniFi infrastructure,
built as a capstone project for the M.S. in Business Information Systems at
Valley City State University.

## Services

| Service | Port | Purpose |
|---|---|---|
| Camera Privacy Toggle | 5000 | Selectively disable/enable cameras for privacy |
| Door Lock Toggle | 5001 | Temporarily unlock/lock doors |
| Hardware Monitor | 5002 | Real-time device health + email alerts |
| Admin Portal | 8080 | Unified tabbed dashboard for all three |

## Setup

Each service has its own directory with a `requirements.txt` and
`config.example.py`. Copy the example to `config.py` and fill in
your controller credentials before running.

See individual README files in each subdirectory for detailed setup.

## Author

Larry Herzog Jr. — March 2026
