# API Reference

<cite>
**Referenced Files in This Document**
- [server.py](file://src/rag/server.py)
- [config.py](file://src/rag/config.py)
- [app.py](file://src/rag/app.py)
- [index.html](file://src/rag/web/index.html)
</cite>

## Update Summary
**Changes Made**
- Restructured documentation to reflect comprehensive API Reference overhaul
- Added complete HTTP Endpoints section with specialized endpoint groups
- Integrated WebSocket Interface documentation
- Enhanced API Reference organization with dedicated endpoint categories
- Updated navigation structure to support modular endpoint documentation

## Table of Contents
1. [Introduction](#introduction)
2. [HTTP Endpoints](#http-endpoints)
3. [WebSocket Interface](#websocket-interface)
4. [Authentication and Authorization](#authentication-and-authorization)
5. [Rate Limiting](#rate-limiting)
6. [Error Handling](#error-handling)
7. [API Versioning](#api-versioning)
8. [Security Considerations](#security-considerations)
9. [Performance Optimization](#performance-optimization)
10. [Practical Usage Examples](#practical-usage-examples)
11. [Integration Patterns](#integration-patterns)
12. [Troubleshooting Guide](#troubleshooting-guide)
13. [Appendices](#appendices)

## Introduction
This document provides comprehensive API documentation for the RAG system's HTTP REST API and WebSocket interfaces. The API exposes a complete set of endpoints for search operations, repository management, indexing control, system status monitoring, and advanced analysis capabilities. The documentation is organized into specialized sections covering different functional domains to facilitate easy navigation and understanding.

The RAG system implements a FastAPI-based HTTP server with robust authentication, rate limiting, and real-time capabilities. All endpoints except `/health` require Bearer token authentication, and the system provides both synchronous and asynchronous operations for various use cases including code search, retrieval-augmented generation, and administrative functions.

**Section sources**
- [server.py:721-789](file://src/rag/server.py#L721-L789)
- [config.py:167-188](file://src/rag/config.py#L167-L188)

## HTTP Endpoints

### Search Endpoints
The search endpoints provide comprehensive code search and retrieval capabilities with hybrid planning, vector similarity, and lexical matching.

#### POST /search
Hybrid planner-driven search with optional repository scoping, filters, and top_k ranking.

**Request Body:**
```json
{
  "query": "string",
  "top_k": 8,
  "filters": {
    "repo": "string",
    "language": ["string"],
    "file_type": "string"
  },
  "rerank": false
}
```

**Response:**
```json
{
  "results": [
    {
      "id": "string",
      "score": 0.95,
      "chunk": "string",
      "metadata": {
        "repo": "string",
        "file": "string",
        "line_start": 1,
        "line_end": 10
      }
    }
  ],
  "query": "string",
  "plan": "string",
  "total": 1,
  "latency_ms": 150
}
```

#### POST /docs-search
Vector search over documentation collection with semantic similarity.

**Request Body:** Same as /search

**Response:** Same as /search

#### POST /context-pack
Token-bounded context slicing with preference for exact matches and lexical hits.

**Request Body:**
```json
{
  "query": "string",
  "max_tokens": 4096,
  "target_rerank": true
}
```

**Response:**
```json
{
  "slices": [
    {
      "text": "string",
      "tokens": 100,
      "reason": "exact_match|lexical_match|semantic",
      "metadata": {}
    }
  ],
  "total_tokens": 100,
  "estimated_cost": 0.0001
}
```

#### POST /enumerate
Exhaustive metadata listing via Qdrant scroll operation.

**Request Body:**
```json
{
  "limit": 100,
  "offset": 0,
  "filters": {}
}
```

**Response:**
```json
{
  "items": [],
  "truncated": false,
  "total": 0
}
```

**Section sources**
- [server.py:1363-1604](file://src/rag/server.py#L1363-L1604)
- [server.py:1606-1635](file://src/rag/server.py#L1606-L1635)
- [server.py:2008-2141](file://src/rag/server.py#L2008-L2141)
- [server.py:2145-2203](file://src/rag/server.py#L2145-L2203)

### Indexing Endpoints
Endpoints for managing repository indexing, job control, and backfill operations.

#### POST /index/start
Queue an asynchronous indexing job for a repository with full or incremental processing options.

**Request Body:**
```json
{
  "repo_path": "/path/to/repo",
  "full": true,
  "include_patterns": ["*.py", "*.js"],
  "exclude_patterns": ["node_modules/", "__pycache__/"]
}
```

**Response:**
```json
{
  "job_id": "string",
  "status": "queued",
  "created_at": "2023-01-01T00:00:00Z"
}
```

#### GET /index/progress/{job_id}
Poll progress and status of a queued indexing job.

**Response:**
```json
{
  "job_id": "string",
  "status": "running|completed|failed",
  "progress": 0.75,
  "processed_files": 150,
  "total_files": 200,
  "errors": []
}
```

#### GET /index/jobs
List all active and completed indexing jobs with filtering options.

**Response:**
```json
{
  "jobs": [
    {
      "job_id": "string",
      "repo_path": "/path/to/repo",
      "status": "string",
      "created_at": "2023-01-01T00:00:00Z",
      "completed_at": "2023-01-01T01:00:00Z"
    }
  ]
}
```

#### POST /index/backfill-code-index
Populate SQLite code_index from Qdrant payloads for legacy compatibility.

**Request Body:** Empty

**Response:**
```json
{
  "status": "backfilled",
  "records_processed": 1000
}
```

#### POST /index
Synchronous indexing of a repository with immediate completion feedback.

**Request Body:** Same as /index/start

**Response:**
```json
{
  "status": "completed",
  "processed_files": 150,
  "embedding_time_ms": 15000,
  "indexing_time_ms": 20000
}
```

#### POST /index/docs
Synchronous indexing of documentation files with separate collection management.

**Request Body:**
```json
{
  "documents": [
    {
      "title": "string",
      "content": "string",
      "url": "string"
    }
  ],
  "collection": "docs"
}
```

**Response:** Same as /index

**Section sources**
- [server.py:1174-1283](file://src/rag/server.py#L1174-L1283)
- [server.py:1288-1361](file://src/rag/server.py#L1288-L1361)
- [server.py:2335-2399](file://src/rag/server.py#L2335-L2399)

### Repository Management Endpoints
Endpoints for repository discovery, configuration, and management operations.

#### GET /repositories
List all indexed repositories with metadata and status information.

**Response:**
```json
{
  "repositories": [
    {
      "path": "/path/to/repo",
      "name": "repo-name",
      "files": 1000,
      "last_indexed": "2023-01-01T00:00:00Z",
      "status": "active"
    }
  ]
}
```

#### POST /repositories/add
Add a new repository to the indexing system with configuration options.

**Request Body:**
```json
{
  "path": "/path/to/repo",
  "name": "repo-name",
  "config": {
    "include_patterns": ["*.py"],
    "exclude_patterns": ["test/"],
    "chunk_size": 512
  }
}
```

**Response:**
```json
{
  "status": "added",
  "repository": {
    "path": "/path/to/repo",
    "name": "repo-name",
    "status": "pending"
  }
}
```

#### DELETE /repositories/remove/{repo_path}
Remove a repository from the indexing system with confirmation.

**Response:**
```json
{
  "status": "removed",
  "path": "/path/to/repo"
}
```

**Section sources**
- [server.py:2400-2541](file://src/rag/server.py#L2400-L2541)

### System Status Endpoints
Comprehensive system health monitoring, statistics, and operational information endpoints.

#### GET /health
Public endpoint reporting component health status including Qdrant, embedder, and Ollama services.

**Response:**
```json
{
  "status": "healthy",
  "components": {
    "qdrant": "healthy",
    "embedder": "healthy",
    "ollama": "healthy"
  },
  "timestamp": "2023-01-01T00:00:00Z"
}
```

#### GET /status
Protected endpoint returning daemon state, embedder information, collections, uptime, and generation model details.

**Response:**
```json
{
  "status": "running",
  "components": {
    "qdrant": "healthy",
    "embedder": "warm",
    "ollama": "ready"
  },
  "collections": ["code", "docs"],
  "uptime_seconds": 3600,
  "files_indexed": 1500,
  "embedder_warm_ms": 150,
  "restart_count": 1,
  "gen_model": "llama3:8b",
  "gen_ctx_size": 8192
}
```

#### GET /metrics
System metrics including query performance, indexing throughput, and resource utilization.

**Response:**
```json
{
  "query_stats": {
    "avg_latency_ms": 150,
    "queries_per_minute": 10,
    "success_rate": 0.95
  },
  "indexing_stats": {
    "files_processed_per_hour": 50,
    "embedding_time_ms": 15000
  },
  "resource_usage": {
    "cpu_percent": 15.5,
    "memory_mb": 256,
    "disk_gb": 1.2
  }
}
```

#### GET /system-info
Detailed system information including configuration, environment variables, and build details.

**Response:**
```json
{
  "version": "1.0.0",
  "build_date": "2023-01-01",
  "environment": "production",
  "config": {
    "host": "localhost",
    "port": 7890,
    "max_workers": 4
  }
}
```

**Section sources**
- [server.py:841-874](file://src/rag/server.py#L841-L874)
- [server.py:877-957](file://src/rag/server.py#L877-L957)

### Advanced Analysis Endpoints
Sophisticated analysis endpoints for code understanding, dependency graphs, and impact assessment.

#### POST /resolve
Resolve symbols to definitions and usages for a named repository with type information.

**Request Body:**
```json
{
  "symbol": "function_name",
  "repo": "repository_name",
  "type": "function|class|variable"
}
```

**Response:**
```json
{
  "symbol": "string",
  "definitions": [
    {
      "file": "string",
      "line": 1,
      "context": "string"
    }
  ],
  "usages": [
    {
      "file": "string",
      "line": 1,
      "context": "string"
    }
  ]
}
```

#### POST /call-tree
Build a call tree for a symbol including caller and callee relationships.

**Request Body:**
```json
{
  "symbol": "function_name",
  "repo": "repository_name",
  "max_depth": 3
}
```

**Response:**
```json
{
  "symbol": "string",
  "call_tree": {
    "function": "string",
    "calls": [
      {
        "function": "string",
        "depth": 1
      }
    ]
  }
}
```

#### POST /graph/impact
Impact analysis including affected files, tests, and downstream dependencies.

**Request Body:**
```json
{
  "files": ["file1.py", "file2.py"],
  "repo": "repository_name"
}
```

**Response:**
```json
{
  "affected_files": ["file3.py", "file4.py"],
  "affected_tests": ["test_file.py"],
  "downstream_dependencies": ["package1", "package2"]
}
```

#### POST /project-understand
High-level project understanding with modules, symbol slices, and architectural insights.

**Request Body:**
```json
{
  "repo": "repository_name",
  "modules": ["core", "utils"]
}
```

**Response:**
```json
{
  "modules": [
    {
      "name": "core",
      "symbols": 50,
      "dependencies": ["utils"]
    }
  ],
  "high_level_summary": "string",
  "key_architectural_patterns": ["pattern1", "pattern2"]
}
```

**Section sources**
- [server.py:1638-1726](file://src/rag/server.py#L1638-L1726)
- [server.py:1728-1896](file://src/rag/server.py#L1728-L1896)
- [server.py:1898-2004](file://src/rag/server.py#L1898-L2004)

## WebSocket Interface

### Connection Establishment
The WebSocket interface provides real-time updates for indexing progress, system events, and live monitoring data.

**Connection URL:** `ws://localhost:7890/ws`

### Message Types and Formats

#### Progress Updates
Real-time progress updates for indexing jobs with detailed status information.

```json
{
  "type": "indexing_progress",
  "job_id": "string",
  "status": "running|completed|failed",
  "progress": 0.75,
  "current_file": "string",
  "processed_files": 150,
  "total_files": 200
}
```

#### System Events
Live system events including health checks, errors, and operational alerts.

```json
{
  "type": "system_event",
  "event_type": "health_check|error|warning",
  "message": "string",
  "timestamp": "2023-01-01T00:00:00Z",
  "details": {}
}
```

#### Query Results
Live streaming of search results with progressive refinement.

```json
{
  "type": "query_result",
  "query_id": "string",
  "result": {
    "chunk": "string",
    "score": 0.95,
    "metadata": {}
  },
  "is_final": false
}
```

### Client Implementation Pattern
```javascript
const socket = new WebSocket('ws://localhost:7890/ws');

socket.onopen = function(event) {
    console.log('Connected to WebSocket');
    // Subscribe to progress updates
    socket.send(JSON.stringify({
        type: 'subscribe',
        channels: ['indexing_progress', 'system_events']
    }));
};

socket.onmessage = function(event) {
    const message = JSON.parse(event.data);
    handleWebSocketMessage(message);
};
```

**Section sources**
- [server.py:2552-2581](file://src/rag/server.py#L2552-L2581)
- [app.py:363-661](file://src/rag/app.py#L363-L661)

## Authentication and Authorization

### Bearer Token Authentication
All endpoints except `/health` require Bearer token authentication via the Authorization header.

**Header Format:**
```
Authorization: Bearer YOUR_ACCESS_TOKEN
```

### Token Management
- **Location:** `~/.rag/token`
- **Creation:** Automatically created if not present
- **Format:** Plain text file containing the token
- **Security:** Constant-time comparison to prevent timing attacks

### Token Generation and Storage
```bash
# Generate token (automatically handled by system)
mkdir -p ~/.rag
echo "your-token-here" > ~/.rag/token

# Use in API requests
curl -H "Authorization: Bearer $(cat ~/.rag/token)" \
     http://localhost:7890/status
```

**Section sources**
- [server.py:592-598](file://src/rag/server.py#L592-L598)
- [config.py:35-50](file://src/rag/config.py#L35-L50)

## Rate Limiting

### Token-Bucket Implementation
The system implements per-token token-bucket rate limiting to prevent abuse and ensure fair usage.

**Configuration:**
- Default tokens per minute: 60
- Burst limit: 10 requests
- Storage: Database-backed token buckets

### Rate Limit Response
```json
{
  "detail": "Rate limit exceeded",
  "reset_time": "2023-01-01T00:00:00Z",
  "remaining_tokens": 0
}
```

### Anonymous Requests
Anonymous requests (without Authorization header) use a fixed token string for rate limiting purposes.

**Section sources**
- [server.py:770-789](file://src/rag/server.py#L770-L789)

## Error Handling

### Standard Error Response Format
```json
{
  "error": {
    "type": "invalid_request_error|authentication_error|rate_limit_error",
    "message": "Error description",
    "code": 400
  }
}
```

### Common HTTP Status Codes
- **200 OK:** Successful request
- **201 Created:** Resource created successfully
- **400 Bad Request:** Invalid request parameters
- **401 Unauthorized:** Missing or invalid authentication
- **403 Forbidden:** Origin mismatch or insufficient permissions
- **404 Not Found:** Resource not found
- **429 Rate Limited:** Exceeded rate limit
- **500 Internal Server Error:** Server-side error
- **502 Bad Gateway:** External service failure

### Error Categories
- **Authentication Errors:** Invalid or missing Bearer tokens
- **Validation Errors:** Invalid request schemas or parameters
- **Rate Limit Errors:** Token bucket exhaustion
- **Service Errors:** External service failures (Qdrant, Ollama)

**Section sources**
- [server.py:741-761](file://src/rag/server.py#L741-L761)
- [server.py:763-768](file://src/rag/server.py#L763-L768)

## API Versioning

### Version Declaration
The server declares its version in the FastAPI factory configuration.

**Current Version:** 1.0.0

### Backward Compatibility
The system maintains backward compatibility with the following policies:

**Deprecated Features:**
- `rerank` field in search requests (ignored but accepted for compatibility)
- Legacy fields in status responses for client parsing continuity

**Migration Path:**
- Remove `rerank` parameter from search requests
- Update client code to handle new response formats
- Monitor deprecation warnings in system logs

**Section sources**
- [server.py:722](file://src/rag/server.py#L722)
- [server.py:38-40](file://src/rag/server.py#L38-L40)

## Security Considerations

### Binding Policy
- **Default Binding:** localhost only
- **Security:** Wildcard bindings are rejected by configuration
- **Production:** Requires explicit configuration for public access

### CSRF Protection
Cross-origin POST/DELETE requests without proper Authorization headers are blocked unless the Origin header matches localhost.

### CORS Configuration
- **Same-Origin Only:** Embedded dashboard operates on same-origin basis
- **Token Injection:** Automatic token injection eliminates CORS concerns
- **External Clients:** Must implement proper origin validation

**Section sources**
- [config.py:35-50](file://src/rag/config.py#L35-L50)
- [server.py:798-815](file://src/rag/server.py#L798-L815)

## Performance Optimization

### Query Optimization Strategies
- **Use /context-pack** for bounded token budgets to reduce LLM costs
- **Prefer /enumerate** for exhaustive metadata queries (note: performs scroll across collection)
- **Monitor /metrics** for latency percentiles and QPM trends
- **Keep top_k reasonable** to avoid excessive retrieval overhead
- **Use repository-scoped collections** to constrain search and improve relevance

### Indexing Performance
- **Incremental Updates:** Use `/index/start` with `full: false` for continuous updates
- **Pattern Filtering:** Configure include/exclude patterns to reduce indexing load
- **Parallel Processing:** Utilize multiple workers for large repositories

### Caching Strategies
- **Embedding Cache:** Warm embedder after initial indexing
- **Query Results:** Implement client-side caching for repeated searches
- **Context Packing:** Cache frequently accessed context slices

## Practical Usage Examples

### Basic Authentication Setup
```bash
# Set up authentication
mkdir -p ~/.rag
echo "your-token-here" > ~/.rag/token

# Verify token location
cat ~/.rag/token
```

### Search Operations
```bash
# Basic search
curl -H "Authorization: Bearer $(cat ~/.rag/token)" \
     -X POST http://localhost:7890/search \
     -d '{"query":"error handling","top_k":8}'

# Repository-scoped search
curl -H "Authorization: Bearer $(cat ~/.rag/token)" \
     -X POST http://localhost:7890/search \
     -d '{"query":"database connection","top_k":8,"filters":{"repo":"my-repo"}}'
```

### Indexing Operations
```bash
# Start indexing job
curl -H "Authorization: Bearer $(cat ~/.rag/token)" \
     -X POST http://localhost:7890/index/start \
     -d '{"repo_path":"/path/to/repo","full":false}'

# Monitor progress
curl -H "Authorization: Bearer $(cat ~/.rag/token)" \
     http://localhost:7890/index/progress/YOUR_JOB_ID

# Force synchronous indexing
curl -H "Authorization: Bearer $(cat ~/.rag/token)" \
     -X POST http://localhost:7890/index \
     -d '{"repo_path":"/path/to/repo","full":true}'
```

### Retrieval-Augmented Generation
```bash
# Ask questions with context
curl -H "Authorization: Bearer $(cat ~/.rag/token)" \
     -X POST http://localhost:7890/ask \
     -d '{"question":"how does the caching work?","top_k":8}'
```

### Real-time Monitoring
```bash
# Connect to WebSocket for live updates
wscat -c ws://localhost:7890/ws

# Subscribe to events
{"type": "subscribe", "channels": ["indexing_progress", "system_events"]}
```

## Integration Patterns

### Client Library Development
```python
import requests
import json

class RAGAPIClient:
    def __init__(self, base_url="http://localhost:7890", token=None):
        self.base_url = base_url
        self.token = token or self._load_token()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        })
    
    def search(self, query, top_k=8, filters=None):
        payload = {"query": query, "top_k": top_k}
        if filters:
            payload["filters"] = filters
            
        response = self.session.post(
            f"{self.base_url}/search",
            data=json.dumps(payload)
        )
        return response.json()
    
    def _load_token(self):
        with open("~/.rag/token", "r") as f:
            return f.read().strip()
```

### Batch Processing Workflow
```bash
#!/bin/bash
# Process multiple queries efficiently

TOKEN=$(cat ~/.rag/token)
BASE_URL="http://localhost:7890"

# Create batch file with queries
cat > queries.txt << EOF
how to implement caching
database connection pooling
error handling patterns
EOF

# Process queries with rate limiting
while IFS= read -r query; do
    echo "Processing: $query"
    curl -H "Authorization: Bearer $TOKEN" \
         -X POST "$BASE_URL/search" \
         -d "{\"query\":\"$query\",\"top_k\":8}"
    sleep 1  # Rate limiting delay
done < queries.txt
```

### Monitoring Integration
```javascript
// Monitor system health and send alerts
setInterval(async () => {
    try {
        const response = await fetch('http://localhost:7890/health');
        const health = await response.json();
        
        if (health.status !== 'healthy') {
            // Send alert notification
            console.error('System unhealthy:', health);
        }
    } catch (error) {
        console.error('Health check failed:', error);
    }
}, 30000); // Check every 30 seconds
```

## Troubleshooting Guide

### Common Issues and Solutions

#### Authentication Problems
- **401 Unauthorized:** Ensure Authorization header contains valid Bearer token from `~/.rag/token`
- **403 Forbidden:** Origin mismatch; ensure requests originate from localhost or include Bearer token
- **Token Issues:** Verify token file exists and has proper permissions

#### Rate Limiting
- **429 Rate Limited:** Wait for token bucket refill or reduce request frequency
- **Anonymous Requests:** Include Authorization header to avoid rate limiting restrictions

#### Service Failures
- **500 Internal Server Error:** Inspect structured logs for failing endpoint; global error handler returns sanitized details
- **502 Bad Gateway during /ask:** LLM generation failed; verify Ollama service availability and model configuration

#### Network Issues
- **Connection Refused:** Verify server is running and listening on correct port
- **WebSocket Connection:** Ensure firewall allows WebSocket connections on same port

### Debugging Tips
- Enable verbose logging for development environments
- Use curl with `-v` flag for detailed request/response inspection
- Monitor system metrics endpoint for performance indicators
- Check event logs for real-time troubleshooting

**Section sources**
- [server.py:741-761](file://src/rag/server.py#L741-L761)
- [server.py:763-768](file://src/rag/server.py#L763-L768)
- [server.py:798-815](file://src/rag/server.py#L798-L815)

## Appendices

### API Reference Structure
The API documentation follows a hierarchical structure designed for easy navigation and comprehensive coverage:

#### Endpoint Categories
- **Search Operations:** Core search and retrieval endpoints
- **Indexing Control:** Repository indexing and job management
- **System Monitoring:** Health, status, and metrics endpoints
- **Advanced Analysis:** Code understanding and dependency analysis
- **Repository Management:** Repository lifecycle operations

#### Documentation Standards
- **Consistent Response Formats:** Standardized success/error response schemas
- **Comprehensive Examples:** Practical curl commands and client patterns
- **Error Handling:** Complete error code coverage and resolution guidance
- **Performance Guidance:** Optimization tips and best practices

### Migration Guide
When upgrading from older versions:

1. **Update Authentication:** Ensure Bearer token implementation is working
2. **Review Deprecated Fields:** Remove `rerank` parameter from search requests
3. **Test WebSocket Integration:** Verify real-time updates are functioning
4. **Update Client Libraries:** Adapt to any response format changes
5. **Monitor Performance:** Track system metrics post-upgrade

### Contributing to API Documentation
- **Report Issues:** Use GitHub issues for documentation gaps
- **Submit Pull Requests:** Contribute improvements to endpoint documentation
- **Provide Examples:** Include practical usage scenarios and edge cases
- **Update Examples:** Keep curl commands and client code current with API changes