pipeline {
  agent any
  options { timestamps(); ansiColor('xterm') }
  environment {
    AI_PLANNER_URL = 'http://ai-planner:8000'
    NPM_CONFIG_CACHE = "${WORKSPACE}/.npm"
    CI = "true"
  }
  stages {
    stage('Checkout') {
        steps {
          script {
            // ensure the workspace is empty (avoids half-baked .git dirs)
            deleteDir()
          }
          // simple declarative git step does init + fetch + checkout
          git url: 'https://github.com/sadiq-git/jenkins', branch: 'master'
      }
    }


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
          def plan = readJSON file: 'ai_plan.json'
          echo "AI Suggested Plan:"
          plan.stages.eachWithIndex { stg, i ->
            echo String.format("  %02d) %s  ::  %s", i+1, stg.name, stg.command)
          }
          // Keep the JSON available for the next stage
          writeFile file: 'ai_plan.lock.json', text: groovy.json.JsonOutput.toJson(plan)
        }
      }
    }

    stage('Execute Plan (Node)') {
      steps {
        script {
          docker.image('node:20-bookworm-slim').inside('-u 0:0') {
            sh '''
              set -e
              apt-get update -y
              DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                git ca-certificates python3 make g++ curl jq
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
  post {
    always { archiveArtifacts artifacts: 'context.json, ai_plan.json, ai_plan.lock.json', onlyIfSuccessful: false }
  }
}
