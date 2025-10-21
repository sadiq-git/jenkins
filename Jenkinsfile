
pipeline {
  agent any
  options {
    timestamps()
    ansiColor('xterm')
  }
  environment {
    // If you add a Jenkins string credential named AI_PLANNER_URL, it will override the default.
    AI_PLANNER_URL = 'http://ai-planner:8000'
  }
  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Collect Context') {
      steps {
        script {
          def ctx = [
            branch:        env.BRANCH_NAME ?: sh(script: "git rev-parse --abbrev-ref HEAD", returnStdout: true).trim(),
            lastCommitMsg: sh(script: "git log -1 --pretty=%B || true", returnStdout: true).trim(),
            buildNumber:   env.BUILD_NUMBER,
            repoName:      env.JOB_NAME,
            culprit:       currentBuild.rawBuild?.getCauses()?.collect{ it.properties }.toString()
          ]
          writeFile file: 'context.json', text: groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(ctx))
          echo "Context:\n${readFile('context.json')}"
        }
      }
    }

    stage('AI Planning (Gemini)') {
      steps {
        script {
          def planJson = sh(
            label: 'Request plan from AI',
            returnStdout: true,
            script: """
              set -e
              curl -sS -X POST "$AI_PLANNER_URL/plan"                 -H 'Content-Type: application/json'                 --data-binary @context.json
            """
          ).trim()

          writeFile file: 'ai_plan.json', text: planJson
          def plan = readJSON file: 'ai_plan.json'

          echo "AI Suggested Plan:"
          plan.stages.eachWithIndex { stg, i ->
            echo String.format("  %02d) %s  ::  %s", i+1, stg.name, stg.command)
          }
        }
      }
    }

    stage('Execute Plan') {
      steps {
        script {
          def plan = readJSON file: 'ai_plan.json'
          plan.stages.each { stg ->
            stage("AI: ${stg.name}") {
              sh label: stg.name, script: stg.command
            }
          }
        }
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: 'context.json, ai_plan.json', onlyIfSuccessful: false
    }
  }
}
