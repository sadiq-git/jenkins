pipeline {
  agent any

  options {
    timestamps()
    ansiColor('xterm')
    skipDefaultCheckout(true) // disable implicit "Declarative: Checkout SCM"
  }

  environment {
    // Pick ONE endpoint style:

    // A) If Jenkins & planner containers share the same Docker network (Compose service name `ai-planner`)
    AI_PLANNER_URL = 'http://ai-planner:8000'

    // B) If you want to hit a planner that’s bound to the host:
    // AI_PLANNER_URL = 'http://host.docker.internal:8000'

    NPM_CONFIG_CACHE = "${WORKSPACE}/.npm"
    CI = "true"
  }

  stages {
    stage('Checkout') {
      steps {
        script { deleteDir() }
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
            branch       : branchGuess,
            lastCommitMsg: sh(script: "git log -1 --pretty=%B || true", returnStdout: true).trim(),
            buildNumber  : env.BUILD_NUMBER as Integer,
            repoName     : env.JOB_NAME
          ]
          writeFile file: 'context.json', text: groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(ctx))
          echo "Context:\n${readFile('context.json')}"
        }
      }
    }

    stage('AI Planning (Gemini)') {
      steps {
        script {
          // Network option A: share Jenkins container network namespace (best if using service name ai-planner)
          def dockerNetOpts = "--network container:${env.HOSTNAME} -u 0:0"
          // Option B (if using host.docker.internal):
          // def dockerNetOpts = "--add-host=host.docker.internal:host-gateway -u 0:0"

          // Single-quoted, so $VARS are expanded by the shell inside the container, not by Groovy.
          def plannerScript = '''
            set -eu

            echo "Planner URL: $AI_PLANNER_URL"

            # Health check; require 200
            hc="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 5 "$AI_PLANNER_URL/healthz" || true)"
            echo "Planner /healthz HTTP: ${hc:-<none>}"
            if [ "$hc" != "200" ]; then
              echo "ERROR: Planner health check failed (got '$hc')."
              exit 2
            fi

            # Request plan (exponential-ish backoff for transient overloads)
            status=""
            for delay in 0 2 4; do
              [ "$delay" -gt 0 ] && sleep "$delay"
              status="$(curl -sS -o ai_plan.raw -w '%{http_code}' \
                        --connect-timeout 10 --max-time 120 \
                        -X POST "$AI_PLANNER_URL/plan" \
                        -H 'Content-Type: application/json' \
                        --data-binary @context.json || true)"
              if [ "$status" = "200" ] && jq -e . ai_plan.raw >/dev/null 2>&1; then
                break
              fi
            done
            echo "$status" > .http_status

            echo "Planner /plan HTTP: $status"
            echo "---- planner raw (first 400 bytes) ----"
            if [ -f ai_plan.raw ]; then head -c 400 ai_plan.raw; else echo "(no body)"; fi
            echo
            echo "---------------------------------------"

            if [ "$status" != "200" ]; then
              echo "ERROR: Planner returned non-200 ($status)."
              exit 3
            fi

            if ! jq -e . ai_plan.raw >/dev/null 2>&1; then
              echo "ERROR: Planner did not return valid JSON."
              exit 4
            fi

            mv ai_plan.raw ai_plan.lock.json
            jq . ai_plan.lock.json > ai_plan.json
          '''.stripIndent()

          docker.image('node-ci:20-bookworm-slim').inside(dockerNetOpts) {
            sh label: 'Request plan from AI (no fallback)', script: plannerScript
          }
        }
      }
    }

    stage('Execute Plan (Node)') {
      steps {
        script {
          if (!fileExists('ai_plan.lock.json')) {
            error "Planner did not produce ai_plan.lock.json; aborting (no fallback allowed)."
          }

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
