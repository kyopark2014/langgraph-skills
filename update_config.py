import json
import os
import sys
import boto3

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "application", "config.json")


def load_existing_config():
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_aws_defaults():
    session = boto3.Session()
    region = session.region_name or "us-west-2"

    sts = boto3.client("sts")
    response = sts.get_caller_identity()
    account_id = response["Account"]

    return region, account_id


def prompt(label, default=None):
    if default:
        value = input(f"{label} [{default}]: ").strip()
        return value if value else default
    else:
        value = input(f"{label}: ").strip()
        return value


def main():
    print("=== Update config.json ===\n")

    config = load_existing_config()

    try:
        print("Fetching AWS account information...")
        region, account_id = get_aws_defaults()
    except Exception as e:
        print(f"Failed to fetch AWS information: {e}", file=sys.stderr)
        region = config.get("region", "us-west-2")
        account_id = config.get("accountId", "")

    config["region"] = region
    config["accountId"] = account_id
    config.setdefault("projectName", "langgraph-skills")
    config.pop("default_skills", None)
    config.pop("default_mcp_servers", None)

    favorite_tools_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "application", "favorite_tools.json"
    )
    if not os.path.exists(favorite_tools_path):
        with open(favorite_tools_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "MCP": ["tavily", "knowledge base", "aws documentation"],
                    "SKILL": ["skill-creator", "docx"],
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"Created: {favorite_tools_path}")

    print(f"  region   : {region}")
    print(f"  accountId: {account_id}\n")

    default_s3 = config.get("s3_bucket") or f"storage-for-rag-project-{account_id}-{region}"
    config["s3_bucket"] = prompt("S3 bucket name", default=default_s3)
    config["knowledge_base_id"] = prompt("Knowledge Base ID", default=config.get("knowledge_base_id"))
    config["tavily_api_key"] = prompt("Tavily API Key", default=config.get("tavily_api_key"))
    if config.get("sharing_url"):
        print(f"  sharing_url: {config['sharing_url']}")
    else:
        print("  sharing_url: (auto-detected on app start via CloudFront)")

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\nSaved: {config_path}")
    print(json.dumps(config, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
