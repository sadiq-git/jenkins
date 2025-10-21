pipeline {
  agent any
  options { timestamps(); ansiColor('xterm') }
  environment {
    AI_PLANNER_URL = 'http://ai-planner:8000'
    // Put npm cache in workspace to persist across runs
    NPM_CONFIG_CACHE = "${WORKSPACE}/.npm"
    CI = "true"
  }
  stages {
    stage('Checkout') { steps { checkout scm } }

    stage('Collect Context') {
      steps {
        script {
          def branchGuess = sh(
            script: "git symbolic-ref -q --short HEAD || git name-rev --name-only HEAD || echo master",
            returnStdout: true
          ).trim()
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
              sh """
                set -e
                curl -sS -X POST "$AI_PLANNER_URL/plan" \
                  -H 'Content-Type: application/json' \
                  --data-binary @context.json > ai_plan.json
                test -s ai_plan.json
              """
            }
          }
          def planText = readFile('ai_plan.json')
          def plan = new groovy.json.JsonSlurperClassic().parseText(planText)

          echo "AI Suggested Plan:"
          plan.stages.eachWithIndex { stg, i ->
            echo String.format("  %02d) %s  ::  %s", i+1, stg.name, stg.command)
          }
          env.AI_PLAN_TEXT = planText
        }
      }
    }

    stage('Execute Plan (Node)') {
      steps {
        script {
          // Always run inside a Node image so npm/node exist
          docker.image('node:20-bookworm-slim').inside('-u 0:0') {
            // Basic tooling for native modules and scripts that need git
            sh '''
              set -e
              apt-get update -y
              DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                git ca-certificates python3 make g++ curl
              mkdir -p "$NPM_CONFIG_CACHE"
            '''

            // Optional: install deps up-front to speed up the AI stages
            sh '''
              if [ -f package-lock.json ]; then
                npm ci --no-audit --prefer-offline || true
              elif [ -f package.json ]; then
                npm install --no-audit --prefer-offline || true
              fi
            '''

            def plan = new groovy.json.JsonSlurperClassic().parseText(env.AI_PLAN_TEXT)
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
  post {
    always { archiveArtifacts artifacts: 'context.json, ai_plan.json', onlyIfSuccessful: false }
  }
}
