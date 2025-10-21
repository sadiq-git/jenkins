pipeline {
  agent any
  options {
    timestamps()
    ansiColor('xterm')
    skipDefaultCheckout(true)   // <— turn off the implicit "Declarative: Checkout SCM"
  }
  environment {
    AI_PLANNER_URL = 'http://ai-planner:8000'
    NPM_CONFIG_CACHE = "${WORKSPACE}/.npm"
    CI = "true"
  }

  stages {
    stage('Checkout') {
      steps {
        script {
          deleteDir()  // ensure no half-baked .git from old runs
        }
        // Initialize repo cleanly; avoids the "not in a git directory" error
        git url: 'https://github.com/sadiq-git/jenkins', branch: 'master'
      }
    }

    stage('Collect Context') {
      steps {
        script {
          def branchGuess = sh(
            script: "git symbolic-ref -q --short HEAD || git name-rev --name-only HEAD || echo master",
            returnStdout: true
          ).trim().replaceFirst(/^remotes\\/origin\\//,'')
          if (!branchGuess || branchGuess == 'HEAD') branchGuess = 'master'
          def ctx = [
            branch: branchGuess,
            lastCommitMsg: sh(script: "git log -1 --pretty=%B || true", returnStdout: true).trim(),
            buildNumber: env.BUILD_NUMBER as Integer,
            repoName: env.JOB_NAME
          ]
          writeFile file: 'context.json', text: groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(ctx))
          echo "Context:\n${readFile('context.json')}"
        }
      }
    }

    stage('AI Planning (Gemini)') {
      steps {
        script {
          timeout(time: 90, unit: 'SECONDS') {
            retry(2) {
              sh '''
                set -euo pipefail

                # 1) Call planner and capture RAW body + status
                status=$(curl -sS -o ai_plan.raw -w "%{http_code}" \
                  -X POST "$AI_PLANNER_URL/plan" \
                  -H 'Content-Type: application/json' \
                  --data-binary @context.json)

                echo "Planner HTTP status: $status"
                echo "---- planner raw (first 400 bytes) ----"
                head -c 400 ai_plan.raw || true
                echo
                echo "---------------------------------------"

                # 2) Extract the LAST JSON object from the raw text (handles prose / code fences)
                python3 - <<'PY'
                import re, json, sys, pathlib
                raw = pathlib.Path("ai_plan.raw").read_text(encoding="utf-8", errors="ignore")

                # Try to find a JSON object ending at EOF using a simple brace counter
                def last_json_object(s):
                    end = len(s) - 1
                    # strip trailing whitespace
                    while end >= 0 and s[end].isspace():
                        end -= 1
                    best = None
                    # scan backwards for a closing brace and attempt to match a balanced object
                    for i in range(end, -1, -1):
                        if s[i] == '}':
                            depth = 0
                            for j in range(i, -1, -1):
                                if s[j] == '}': depth += 1
                                elif s[j] == '{':
                                    depth -= 1
                                    if depth == 0:
                                        best = s[j:i+1]
                                        break
                            if best:
                                break
                    return best

                snippet = last_json_object(raw)
                if not snippet:
                    print("ERROR: No JSON object found at end of response", file=sys.stderr)
                    sys.exit(2)

                try:
                    obj = json.loads(snippet)
                except Exception as e:
                    print("ERROR: Extracted JSON failed to parse:", e, file=sys.stderr)
                    print(snippet[:400], file=sys.stderr)
                    sys.exit(3)

                # Write the cleaned JSON for the next steps
                pathlib.Path("ai_plan.json").write_text(json.dumps(obj), encoding="utf-8")
                PY

                            # 3) Validate JSON is actually JSON (pretty-print or fail)
                            jq . ai_plan.json >/dev/null
                          '''
            }
          }

          // Show plan and save a locked copy
          def plan = readJSON file: 'ai_plan.json'
          echo "AI Suggested Plan:"
          plan.stages.eachWithIndex { stg, i ->
            echo String.format("  %02d) %s  ::  %s", i+1, stg.name, stg.command)
          }
          writeFile file: 'ai_plan.lock.json', text: groovy.json.JsonOutput.toJson(plan)
        }
      }
    }
    
    stage('Execute Plan (Node)') {
      steps {
        script {
          // read context to export env vars for plan stages
          def ctx = readJSON file: 'context.json'
          withEnv(["BRANCH=${ctx.branch}", "REPO_NAME=${ctx.repoName}"]) {
            docker.image('node-ci:20-bookworm-slim').inside('-u 0:0') {
              sh '''
                set -e
                mkdir -p "$NPM_CONFIG_CACHE"
                if [ -f package-lock.json ]; then
                  npm ci --no-audit --prefer-offline || true
                elif [ -f package.json ]; then
                  npm install --no-audit --prefer-offline || true
                fi
              '''
              def plan = readJSON file: 'ai_plan.lock.json'
              plan.stages.each { stg ->
                stage("AI: ${stg.name}") {
                  sh label: stg.name, script: stg.command
                }
              }
            }
          }
        }
      }
    }
  } 
  post {
    always {
      archiveArtifacts artifacts: 'context.json, ai_plan.json, ai_plan.lock.json', onlyIfSuccessful: false
    }
  }
}
