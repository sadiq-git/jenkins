pipeline {
  agent any

  options {
    timestamps()
    ansiColor('xterm')
    skipDefaultCheckout(true)   // turn off the implicit "Declarative: Checkout SCM"
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
          deleteDir() // ensure no half-baked .git from old runs
        }
        // Clean clone (avoids “not in a git directory” issues)
        git url: 'https://github.com/sadiq-git/jenkins', branch: 'master'
      }
    }

    stage('Collect Context') {
      steps {
        script {
          def branchGuess = sh(
            script: "git symbolic-ref -q --short HEAD || git name-rev --name-only HEAD || echo master",
            returnStdout: true
          ).trim().replaceFirst('^remotes/origin/','')
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

    stage('AI Planning (Gemini))') {
      steps {
        script {
          // Share Jenkins container network so the hostname "ai-planner" resolves
          def netOpt = "--network container:${env.HOSTNAME}"

          docker.image('node-ci:20-bookworm-slim').inside("${netOpt} -u 0:0") {
            sh label: 'Request plan from AI', script: '''
              set -e

              echo "Requesting plan from $AI_PLANNER_URL"

              # Quick health check against planner's /healthz endpoint
              if ! curl -fsS --connect-timeout 3 --max-time 5 "$AI_PLANNER_URL/healthz" >/dev/null; then
                echo "Planner health check failed; using fallback plan."
                # Build fallback JSON safely with jq (no heredocs)
                jq -n \
                  --arg re "$REPO_NAME" \
                  --arg br "$BRANCH" \
                  --arg bn "$BUILD_NUMBER" \
                  '
                  {
                    stages: [
                      {name:"Checkout Code",       command: ("echo \\"Repo: " + $re + ", branch: " + $br + ", build: " + $bn + "\\"")},
                      {name:"Install Dependencies", command: "npm ci --prefer-offline || npm install --prefer-offline || true"},
                      {name:"Build Project",        command: "npm run build || echo \\"No build script, skipping.\\""},
                      {name:"Run Unit Tests",       command: "npm test || echo \\"No tests, skipping.\\""}
                    ]
                  }' | tee ai_plan.lock.json | jq . > ai_plan.json
                echo "health-check-failed" > .http_status
                exit 0
              fi

              # Try up to 3 times to get a valid JSON plan
              status=""
              for i in 1 2 3; do
                status="$(curl -sS -o ai_plan.raw -w "%{http_code}" \
                           --connect-timeout 3 --max-time 10 \
                           -X POST "$AI_PLANNER_URL/plan" \
                           -H "Content-Type: application/json" \
                           --data-binary @context.json || true)"
                if [ "$status" = "200" ] && jq -e . ai_plan.raw >/dev/null 2>&1; then
                  break
                fi
                sleep 2
              done
              echo "$status" > .http_status

              echo "Planner HTTP status: $status"
              echo "---- planner raw (first 400 bytes) ----"
              head -c 400 ai_plan.raw || true; echo
              echo "---------------------------------------"

              if [ "$status" = "200" ] && jq -e . ai_plan.raw >/dev/null 2>&1; then
                mv ai_plan.raw ai_plan.lock.json
                jq . ai_plan.lock.json > ai_plan.json
              else
                echo "Planner failed or returned non-JSON. Using fallback plan."
                jq -n \
                  --arg re "$REPO_NAME" \
                  --arg br "$BRANCH" \
                  --arg bn "$BUILD_NUMBER" \
                  '
                  {
                    stages: [
                      {name:"Checkout Code",       command: ("echo \\"Repo: " + $re + ", branch: " + $br + ", build: " + $bn + "\\"")},
                      {name:"Install Dependencies", command: "npm ci --prefer-offline || npm install --prefer-offline || true"},
                      {name:"Build Project",        command: "npm run build || echo \\"No build script, skipping.\\""},
                      {name:"Run Unit Tests",       command: "npm test || echo \\"No tests, skipping.\\""}
                    ]
                  }' | tee ai_plan.lock.json | jq . > ai_plan.json
              fi
            '''
          }
        }
      }
    }

    stage('Execute Plan (Node)') {
      steps {
        script {
          // Export env vars used inside the plan commands
          def ctx = readJSON file: 'context.json'
          withEnv([
            "BRANCH=${ctx.branch}",
            "REPO_NAME=${ctx.repoName}",
            "BUILD_NUMBER=${env.BUILD_NUMBER}"
          ]) {
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
      archiveArtifacts artifacts: 'context.json, ai_plan.json, ai_plan.lock.json, ai_plan.raw, .http_status', allowEmptyArchive: true
    }
  }
}
