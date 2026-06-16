"""Shared technical-skill detection patterns.

Dependency-free module: defines the regex → canonical-label table used to
mine known technical skills from free text. Lives at the app root (not under
``app.services``) so both the candidate mapper and Agent1's normaliser can
import it without triggering ``app.services.__init__`` (which eagerly loads
SearchService → graph.nodes → Agent1, creating a circular import).
"""

from __future__ import annotations

from typing import Final

# (regex pattern, canonical label). Patterns are matched case-insensitively.
KNOWN_SKILL_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    # Languages
    (r"\bjava\b", "Java"),
    (r"\bj2ee\b", "J2EE"),
    (r"\bc\+\+", "C++"),
    (r"\bc#\b", "C#"),
    (r"\bpython\b", "Python"),
    (r"\bphp\b", "PHP"),
    (r"\b\.net\b", ".NET"),
    (r"\bscala\b", "Scala"),
    (r"\bkotlin\b", "Kotlin"),
    (r"\brust\b", "Rust"),
    (r"\bgo\b|\bgolang\b", "Go"),
    (r"\bswift\b", "Swift"),
    (r"\btyescript\b|\bts\b", "TypeScript"),
    (r"\bjavascript\b|\bjs\b", "JavaScript"),
    # Frameworks / libs
    (r"\bspring\s*boot\b", "Spring Boot"),
    (r"\bspring\b", "Spring"),
    (r"\bhibernate\b", "Hibernate"),
    (r"\bjsp\b", "JSP"),
    (r"\bjsf\b", "JSF"),
    (r"\bstruts\b", "Struts"),
    (r"\bangular\b", "Angular"),
    (r"\breact\b", "React"),
    (r"\bvue\b", "Vue.js"),
    (r"\bnode(?:\.js)?\b", "Node.js"),
    (r"\bdjango\b", "Django"),
    (r"\bflask\b", "Flask"),
    # Data / messaging
    (r"\bkafka\b", "Kafka"),
    (r"\brabbit\s*mq\b", "RabbitMQ"),
    (r"\belastic\s*search\b|\belasticsearch\b", "Elasticsearch"),
    (r"\bspark\b", "Spark"),
    (r"\bhadoop\b", "Hadoop"),
    # Databases
    (r"\bsql\b", "SQL"),
    (r"\bpostgre\b|\bpostgresql\b", "PostgreSQL"),
    (r"\bmysql\b", "MySQL"),
    (r"\boracle\b", "Oracle"),
    (r"\bmongo\s*db\b|\bmongodb\b", "MongoDB"),
    (r"\bredis\b", "Redis"),
    # Infrastructure / cloud
    (r"\bdocker\b", "Docker"),
    (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
    (r"\baws\b", "AWS"),
    (r"\bazure\b", "Azure"),
    (r"\bgcp\b|\bgoogle\s*cloud\b", "GCP"),
    (r"\bjenkins\b", "Jenkins"),
    (r"\bci\s*/\s*cd\b|\bcicd\b", "CI/CD"),
    (r"\bdevops\b", "DevOps"),
    (r"\bterraform\b", "Terraform"),
    # Finance / domain
    (r"\bfixe[sd]?\s*income\b|\bobligations?\b", "Produits de taux"),
    (r"\bderivativ[esi]+\b|\bderivés?\b", "Dérivés"),
    (r"\bmarket\s*data\b", "Market Data"),
    (r"\bfrontoffice\b|\bfront\s*office\b", "Front Office"),
    (r"\bmiddleoffice\b|\bmiddle\s*office\b", "Middle Office"),
    (r"\brisque?\b|\brisk\b", "Gestion du risque"),
    (r"\btrading\b", "Trading"),
    (r"\bbloomberg\b", "Bloomberg"),
    (r"\breuters\b|\brefinitiv\b", "Reuters/Refinitiv"),
    # Frontend
    (r"\bfront[-\s]?end\b", "Front-end"),
    (r"\bback[-\s]?end\b", "Back-end"),
    (r"\bmicroservice", "Microservices"),
    (r"\bapi\s*rest\b|\brestful\b|\brest\s*api\b", "REST API"),
    (r"\bsoap\b", "SOAP"),
    (r"\bxml\b", "XML"),
    (r"\bjson\b", "JSON"),
    (r"\bgit\b", "Git"),
    (r"\bscrum\b|\bagile\b", "Agile/Scrum"),
    (r"\bjira\b", "Jira"),
)

__all__ = ["KNOWN_SKILL_PATTERNS"]
