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
              docker.image('node-ci:20-bookworm-slim').inside('-u 0:0') {
                sh '''
                  set -eu pipefail

                  # Call planner
                  status=$(curl -sS -o ai_plan.raw -w "%{http_code}" \
                    -X POST "$AI_PLANNER_URL/plan" \
                    -H 'Content-Type: application/json' \
                    --data-binary @context.json)

                  echo "Planner HTTP status: $status"
                  echo "---- planner raw (first 400 bytes) ----"
                  head -c 400 ai_plan.raw || true
                  echo
                  echo "---------------------------------------"

                  # Try the fast path: valid JSON already?
                  if jq -e . ai_plan.raw >/dev/null 2>&1; then
                    jq . ai_plan.raw > ai_plan.json
                    exit 0
                  fi

                  # Fallback: extract the last balanced JSON object with Python
                  python3 - <<'PY'
                  import json, pathlib
                  s = pathlib.Path("ai_plan.raw").read_text(encoding="utf-8", errors="ignore")
                  best = None
                  end = len(s) - 1
                  while end >= 0 and s[end].isspace(): end -= 1
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
                          if best: break
                  if not best:
                      raise SystemExit("No JSON object found at end of response")
                  obj = json.loads(best)
                  pathlib.Path("ai_plan.json").write_text(json.dumps(obj), encoding="utf-8")
                  PY

                  # Validate the cleaned JSON
                  jq . ai_plan.json >/dev/null
                '''
              }
            }
          }

          // Show + lock the plan
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
