# Deployment and Operations

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [compose.qdrant.yml](file://compose.qdrant.yml)
- [config/default.toml](file://config/default.toml)
- [src/rag/config.py](file://src/rag/config.py)
- [src/rag/server.py](file://src/rag/server.py)
- [src/rag/integration/supervisor.py](file://src/rag/integration/supervisor.py)
- [src/rag/integration/logging_setup.py](file://src/rag/integration/logging_setup.py)
- [src/rag/integration/claude_code.py](file://src/rag/integration/claude_code.py)
- [src/rag/cli.py](file://src/rag/cli.py)
- [docs/deployment-linux.md](file://docs/deployment-linux.md)
- [docs/ADR/001-full-stack-decision.md](file://docs/ADR/001-full-stack-decision.md)
- [scripts/install-codex-skills.sh](file://scripts/install-codex-skills.sh)
- [pyproject.toml](file://pyproject.toml)
</cite>

## Update Summary
**Changes Made**
- Complete restructuring of deployment documentation into specialized sections
- Added comprehensive Deployment Strategies section covering Docker Compose, Kubernetes, and bare metal installations
- Created dedicated Monitoring and Logging section with health checks and observability
- Established Scaling and Maintenance section for high availability and performance
- Developed Security and Configuration section for hardened deployments
- Integrated all existing operational content into structured sections

## Table of Contents
1. [Introduction](#introduction)
2. [Deployment Strategies](#deployment-strategies)
3. [Monitoring and Logging](#monitoring-and-logging)
4. [Scaling and Maintenance](#scaling-and-maintenance)
5. [Security and Configuration](#security-and-configuration)
6. [Common Operational Scenarios](#common-operational-scenarios)
7. [Troubleshooting Guide](#troubleshooting-guide)
8. [Conclusion](#conclusion)

## Introduction
This comprehensive deployment and operations guide provides production-focused guidance for the RAG system across multiple deployment environments. The documentation is organized into specialized sections covering deployment strategies, monitoring and logging, scaling and maintenance, and security configurations. It addresses supervised daemon architecture, auto-start mechanisms, health monitoring, scaling considerations, backup and recovery procedures, and security hardening for Docker Compose, Kubernetes, and bare metal installations.

## Deployment Strategies

### Docker Compose (Local Qdrant Server)
The RAG system supports containerized deployment using Docker Compose for local development and testing environments. The provided Compose file orchestrates the Qdrant vector database alongside the RAG daemon.

**Key Features:**
- Persistent volume mounting for Qdrant data
- Network isolation between containers
- Environment variable configuration
- Health check integration

**Deployment Steps:**
1. Configure Qdrant settings in default.toml
2. Start services with docker-compose up -d
3. Verify service health and connectivity
4. Access the RAG API at http://localhost:7890

**Section sources**
- [compose.qdrant.yml:1-11](file://compose.qdrant.yml#L1-L11)
- [config/default.toml:21-26](file://config/default.toml#L21-L26)

### Kubernetes Deployment (Production)
For production Kubernetes deployments, the RAG system can be containerized and deployed as a StatefulSet with persistent storage and horizontal scaling capabilities.

**Kubernetes Architecture:**
- StatefulSet for stable network identity
- PersistentVolumeClaims for Qdrant data persistence
- ConfigMaps for configuration management
- Service mesh integration for traffic management
- PodDisruptionBudget for high availability

**Deployment Components:**
- RAG Daemon Pod with resource limits
- Sidecar container for Qdrant (if using embedded mode)
- Ingress controller for external access
- Secret management for bearer tokens
- HorizontalPodAutoscaler for dynamic scaling

**Section sources**
- [src/rag/server.py:603-716](file://src/rag/server.py#L603-L716)
- [src/rag/config.py:35-131](file://src/rag/config.py#L35-L131)

### Bare Metal Installation (macOS and Linux)
Direct installation on physical hardware provides optimal performance and control over system resources.

**macOS Installation:**
- Launchd service configuration for auto-start
- Home directory permissions and ownership
- Background process supervision
- System integration for crash recovery

**Linux Installation:**
- User-level systemd units for session persistence
- Lingering enabled for logout resilience
- Environment variable configuration
- Journal logging integration

**Installation Process:**
1. Create ~/.rag directory structure
2. Configure service permissions
3. Install launchd/systemd service
4. Start supervised daemon
5. Verify service status and health

**Section sources**
- [src/rag/integration/supervisor.py:75-153](file://src/rag/integration/supervisor.py#L75-L153)
- [docs/deployment-linux.md:1-57](file://docs/deployment-linux.md#L1-L57)

## Monitoring and Logging

### Health Checks and Status Endpoints
The RAG daemon provides comprehensive health monitoring through REST API endpoints designed for automated monitoring systems.

**Health Endpoint (/health):**
- Aggregates component readiness status
- Validates Qdrant connection and availability
- Checks Ollama service health
- Returns aggregated system status

**Status Endpoint (/status):**
- Protected by bearer token authentication
- Returns embedder model information
- Provides collection statistics
- Reports uptime and restart counts
- Includes file indexing metrics

**Section sources**
- [src/rag/server.py:858-874](file://src/rag/server.py#L858-L874)
- [src/rag/server.py:878-902](file://src/rag/server.py#L878-L902)

### Logging Configuration and Rotation
Structured logging with rotation prevents disk space issues in production environments while maintaining audit trails.

**Logging Architecture:**
- JSON-formatted structured logs
- 10MB file size limit with 5 backup retention
- Automatic rotation on size threshold
- Uvicorn logging disabled to prevent duplication
- Centralized log location at ~/.rag/logs/

**Log Categories:**
- Daemon lifecycle events
- Request/response traces
- Error conditions and exceptions
- Performance metrics and timing
- Security events and authentication

**Section sources**
- [src/rag/integration/logging_setup.py:38-108](file://src/rag/integration/logging_setup.py#L38-L108)

### Diagnostics and Troubleshooting
Comprehensive diagnostic tools help operators quickly identify and resolve operational issues.

**Diagnostic Commands:**
- Health check aggregation across all components
- Cache statistics and memory usage
- File system monitoring and disk space
- Network connectivity verification
- Service dependency validation

**Section sources**
- [src/rag/cli.py:33-48](file://src/rag/cli.py#L33-L48)
- [src/rag/cli.py:2098-2141](file://src/rag/cli.py#L2098-L2141)

## Scaling and Maintenance

### Horizontal Scaling Considerations
The current RAG implementation is designed around a single supervised daemon architecture. Horizontal scaling requires careful consideration of shared state and coordination.

**Current Limitations:**
- Single point of failure in current design
- No built-in clustering or consensus mechanisms
- Shared filesystem requirements for persistence
- Token-based authentication per instance

**Scaling Approaches:**
- Load balancing with sticky sessions
- Shared storage backend for Qdrant data
- Reverse proxy with bearer token forwarding
- Database-backed session management

**Section sources**
- [src/rag/config.py:39-50](file://src/rag/config.py#L39-L50)
- [README.md:67-74](file://README.md#L67-L74)

### Load Balancing and High Availability
Production deployments should implement load balancing and redundancy to ensure continuous availability.

**Load Balancer Configuration:**
- Sticky session configuration for token-based auth
- Health check endpoint integration
- SSL termination and certificate management
- Connection pooling and timeout settings

**High Availability Patterns:**
- Multiple daemon instances behind load balancer
- Automated failover detection
- Graceful shutdown handling
- Circuit breaker pattern for external services

**Section sources**
- [docs/deployment-linux.md:51-57](file://docs/deployment-linux.md#L51-L57)
- [src/rag/server.py:603-716](file://src/rag/server.py#L603-L716)

### Maintenance Procedures
Regular maintenance ensures optimal performance and system reliability.

**Scheduled Maintenance Tasks:**
- Index integrity verification and repair
- Log rotation and cleanup
- Cache optimization and pruning
- Dependency updates and security patches
- Performance monitoring and alerting

**Maintenance Windows:**
- Planned downtime for major updates
- Rolling restart procedures
- Data backup verification
- Performance baseline establishment

**Section sources**
- [src/rag/cli.py:2098-2141](file://src/rag/cli.py#L2098-L2141)
- [src/rag/cli.py:302-385](file://src/rag/cli.py#L302-L385)

## Security and Configuration

### Authentication and Authorization
The RAG system implements bearer token authentication for protecting sensitive endpoints and operations.

**Token Management:**
- Secure token storage in ~/.rag/token
- Restricted file permissions (600)
- Token rotation and renewal procedures
- Multi-instance token synchronization

**Authentication Flow:**
- Bearer token required for protected endpoints
- CLI and TUI clients share authentication
- Token validation middleware implementation
- Session management and expiration handling

**Section sources**
- [src/rag/config.py:167-189](file://src/rag/config.py#L167-L189)
- [src/rag/server.py:592-598](file://src/rag/server.py#L592-L598)

### Network Security and Firewall Configuration
Production deployments require careful network security configuration to protect against unauthorized access.

**Network Architecture:**
- Localhost binding with reverse proxy for external access
- TLS termination at load balancer or reverse proxy
- Port-based access control and firewall rules
- Network segmentation and VLAN configuration

**Security Headers and Controls:**
- CSRF protection middleware
- CORS configuration for web interface
- Rate limiting and request throttling
- Input validation and sanitization

**Section sources**
- [src/rag/config.py:39-50](file://src/rag/config.py#L39-L50)
- [src/rag/server.py:790-800](file://src/rag/server.py#L790-L800)

### Configuration Management
Centralized configuration management ensures consistent deployment across environments.

**Configuration Layers:**
- Default values in TOML configuration
- Environment-specific overrides
- Runtime parameter validation
- Configuration hot-reload capabilities

**Security Configuration:**
- Encrypted secrets management
- Environment variable injection
- Configuration validation and sanitization
- Audit logging for configuration changes

**Section sources**
- [src/rag/config.py:35-131](file://src/rag/config.py#L35-L131)
- [config/default.toml:1-41](file://config/default.toml#L1-L41)

## Common Operational Scenarios

### Initial System Setup and Configuration
Complete step-by-step procedure for first-time system deployment and configuration.

**Setup Steps:**
1. Create configuration directory structure
2. Configure server settings and authentication
3. Set up Qdrant vector database
4. Configure embedding service (Ollama)
5. Initialize supervised daemon service
6. Verify system health and connectivity

**Verification Checklist:**
- Health endpoint returns success status
- Status endpoint provides expected metrics
- Authentication works for protected endpoints
- Logging shows normal operational messages

**Section sources**
- [src/rag/cli.py:82-141](file://src/rag/cli.py#L82-L141)
- [src/rag/cli.py:33-48](file://src/rag/cli.py#L33-L48)

### Repository Indexing and Content Management
Comprehensive guide for managing code repositories and content indexing operations.

**Indexing Workflow:**
- Repository discovery and scanning
- Code chunking and embedding generation
- Vector database population and optimization
- Incremental update processing
- Index integrity verification

**Content Management:**
- Repository exclusion patterns
- File type filtering and processing
- Large file handling and skip policies
- Encoding detection and conversion

**Section sources**
- [src/rag/cli.py:246-300](file://src/rag/cli.py#L246-L300)
- [src/rag/cli.py:2098-2141](file://src/rag/cli.py#L2098-L2141)

### External Service Integration
Integration with external services including Claude Code and Codex skills.

**Claude Code Integration:**
- Slash command generation and registration
- Hook installation and configuration
- Command routing and response handling
- Error handling and fallback mechanisms

**Codex Skills Integration:**
- Skill package installation and management
- Skill discovery and loading
- Dependency resolution and validation
- Update and version management

**Section sources**
- [src/rag/integration/claude_code.py:49-120](file://src/rag/integration/claude_code.py#L49-L120)
- [scripts/install-codex-skills.sh:1-28](file://scripts/install-codex-skills.sh#L1-L28)

## Troubleshooting Guide

### System Health and Connectivity Issues
Diagnostic procedures for identifying and resolving common operational problems.

**Health Check Procedures:**
- Verify daemon process status and PID
- Check Qdrant service connectivity and availability
- Validate Ollama service health and model availability
- Test bearer token authentication
- Review system resource utilization

**Connectivity Troubleshooting:**
- Network path verification and routing
- Port accessibility and firewall rules
- DNS resolution and hostname configuration
- Proxy configuration and SSL certificate validation

**Section sources**
- [src/rag/cli.py:33-48](file://src/rag/cli.py#L33-L48)
- [src/rag/server.py:858-874](file://src/rag/server.py#L858-L874)

### Performance and Resource Issues
Identification and resolution of performance bottlenecks and resource constraints.

**Performance Monitoring:**
- Embedding throughput measurement and optimization
- Memory usage and garbage collection patterns
- Disk I/O and storage performance metrics
- Network latency and bandwidth utilization

**Resource Optimization:**
- CPU and memory allocation tuning
- Connection pool sizing and management
- Cache configuration and eviction policies
- Batch processing and queue management

**Section sources**
- [src/rag/cli.py:302-385](file://src/rag/cli.py#L302-L385)
- [src/rag/server.py:645-655](file://src/rag/server.py#L645-L655)

### Backup and Recovery Operations
Comprehensive backup and disaster recovery procedures for production environments.

**Backup Strategy:**
- Token file backup with encryption
- Qdrant data directory backup and compression
- Collection-level backup and restore procedures
- Incremental backup scheduling and retention

**Recovery Procedures:**
- Partial recovery from corrupted indices
- Full system restoration from backups
- Rollback procedures for failed updates
- Disaster recovery testing and validation

**Section sources**
- [src/rag/config.py:167-189](file://src/rag/config.py#L167-L189)
- [src/rag/cli.py:60-66](file://src/rag/cli.py#L60-L66)

## Conclusion
The RAG system provides a comprehensive deployment and operations framework suitable for various production environments. The modular documentation structure enables operators to focus on specific operational aspects while maintaining system reliability and security. By following the deployment strategies, monitoring practices, scaling guidelines, and security configurations outlined in this document, organizations can successfully operate the RAG system in production environments with confidence in its stability, performance, and security posture.