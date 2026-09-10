SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS classes (
  class_id VARCHAR(64) NOT NULL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  grade VARCHAR(32) NULL,
  subject VARCHAR(64) NULL,
  teacher_id VARCHAR(64) NULL,
  KEY idx_classes_teacher (teacher_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS students (
  student_id VARCHAR(64) NOT NULL PRIMARY KEY,
  student_no VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  UNIQUE KEY uk_students_no (student_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS enrollments (
  class_id VARCHAR(64) NOT NULL,
  student_id VARCHAR(64) NOT NULL,
  PRIMARY KEY (class_id, student_id),
  CONSTRAINT fk_enroll_class FOREIGN KEY (class_id) REFERENCES classes (class_id),
  CONSTRAINT fk_enroll_student FOREIGN KEY (student_id) REFERENCES students (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assignments (
  homework_id VARCHAR(64) NOT NULL PRIMARY KEY,
  class_id VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  subject VARCHAR(64) NULL,
  knowledge_points JSON NULL,
  paper_path VARCHAR(1024) NULL,
  extra JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_assign_class FOREIGN KEY (class_id) REFERENCES classes (class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS items (
  homework_id VARCHAR(64) NOT NULL,
  item_id VARCHAR(64) NOT NULL,
  kind ENUM('objective','subjective') NOT NULL,
  number INT NOT NULL,
  stem TEXT NULL,
  options JSON NULL,
  answer_key JSON NULL,
  rubric JSON NULL,
  knowledge_point VARCHAR(255) NULL,
  score DECIMAL(8,2) NULL,
  PRIMARY KEY (homework_id, item_id),
  CONSTRAINT fk_items_hw FOREIGN KEY (homework_id) REFERENCES assignments (homework_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS card_templates (
  homework_id VARCHAR(64) NOT NULL PRIMARY KEY,
  geometry JSON NOT NULL,
  print_path VARCHAR(1024) NULL,
  CONSTRAINT fk_tmpl_hw FOREIGN KEY (homework_id) REFERENCES assignments (homework_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS scans (
  scan_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  homework_id VARCHAR(64) NOT NULL,
  student_id VARCHAR(64) NULL,
  file_path VARCHAR(1024) NOT NULL,
  status VARCHAR(32) NOT NULL,
  CONSTRAINT fk_scans_hw FOREIGN KEY (homework_id) REFERENCES assignments (homework_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS item_results (
  homework_id VARCHAR(64) NOT NULL,
  student_id VARCHAR(64) NOT NULL,
  item_id VARCHAR(64) NOT NULL,
  raw JSON NULL,
  score DECIMAL(8,2) NULL,
  is_correct TINYINT NULL,
  source ENUM('omr','ocr_llm','teacher') NOT NULL,
  pending TINYINT NOT NULL DEFAULT 1,
  PRIMARY KEY (homework_id, student_id, item_id),
  CONSTRAINT fk_res_hw FOREIGN KEY (homework_id) REFERENCES assignments (homework_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS review_queue (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  homework_id VARCHAR(64) NOT NULL,
  student_id VARCHAR(64) NULL,
  item_id VARCHAR(64) NULL,
  reason VARCHAR(64) NOT NULL,
  suggested_score DECIMAL(8,2) NULL,
  status ENUM('open','accepted','overridden') NOT NULL DEFAULT 'open'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS conversations (
  conversation_id VARCHAR(64) NOT NULL PRIMARY KEY,
  homework_id VARCHAR(64) NULL,
  class_id VARCHAR(64) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS messages (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  conversation_id VARCHAR(64) NOT NULL,
  role VARCHAR(32) NOT NULL,
  content MEDIUMTEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_msg_conv FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS insight_snapshots (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  homework_id VARCHAR(64) NULL,
  class_id VARCHAR(64) NOT NULL,
  scope ENUM('student','class') NOT NULL,
  `window` ENUM('short','long') NOT NULL,
  student_id VARCHAR(64) NULL,
  payload JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mastery_events (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  student_id VARCHAR(64) NOT NULL,
  homework_id VARCHAR(64) NOT NULL,
  knowledge_point VARCHAR(255) NOT NULL,
  mastery ENUM('mastered','weak','untested') NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS a2a_tasks (
  task_id VARCHAR(64) NOT NULL PRIMARY KEY,
  homework_id VARCHAR(64) NULL,
  skill VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  payload JSON NULL,
  result JSON NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS embedding_meta (
  faiss_id INT NOT NULL,
  kind ENUM('item','wrong','knowledge') NOT NULL,
  ref_id VARCHAR(128) NOT NULL,
  homework_id VARCHAR(64) NULL,
  text_hash VARCHAR(64) NOT NULL,
  UNIQUE KEY uk_faiss_id (faiss_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS teachers (
  teacher_id VARCHAR(64) NOT NULL PRIMARY KEY,
  username VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  last_class_id VARCHAR(64) NULL,
  last_homework_id VARCHAR(64) NULL,
  last_page VARCHAR(32) NULL,
  UNIQUE KEY uk_teachers_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS teacher_sessions (
  token VARCHAR(128) NOT NULL PRIMARY KEY,
  teacher_id VARCHAR(64) NOT NULL,
  expires_at DATETIME NOT NULL,
  KEY idx_teacher_sessions_teacher (teacher_id),
  KEY idx_teacher_sessions_exp (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
