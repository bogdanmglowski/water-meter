use std::fs;
use std::path::{Component, Path, PathBuf};

use crate::error::{AppError, AppResult};
use crate::models::{
    ReaderGalleryResponse, ReaderGallerySection, ReaderImageDayGroup, ReaderImageItem,
};

const CURRENT_CROP_NAME: &str = "meter-crop.png";

pub fn build_gallery(
    reader_runtime_dir: &Path,
    original_page: usize,
    processed_page: usize,
    page_size: usize,
) -> AppResult<ReaderGalleryResponse> {
    let current_crop_path = reader_runtime_dir.join(CURRENT_CROP_NAME);
    let current_crop_url = current_crop_path
        .is_file()
        .then(|| format!("/api/reader/images/current/{CURRENT_CROP_NAME}"));

    Ok(ReaderGalleryResponse {
        current_crop_url,
        original_images: paginate_day_groups(
            collect_images(&reader_runtime_dir.join("pictures"), "original")?,
            original_page,
            page_size,
        ),
        processed_images: paginate_day_groups(
            collect_images(&reader_runtime_dir.join("processed"), "processed")?,
            processed_page,
            page_size,
        ),
    })
}

pub fn resolve_image_path(
    reader_runtime_dir: &Path,
    category: &str,
    relative_path: &str,
) -> AppResult<PathBuf> {
    let root = match category {
        "current" => reader_runtime_dir.to_path_buf(),
        "original" => reader_runtime_dir.join("pictures"),
        "processed" => reader_runtime_dir.join("processed"),
        other => {
            return Err(AppError::NotFound(format!(
                "reader image category '{other}' was not found"
            )));
        }
    };

    let relative = Path::new(relative_path);
    if relative.is_absolute()
        || relative
            .components()
            .any(|component| matches!(component, Component::ParentDir | Component::RootDir | Component::Prefix(_)))
    {
        return Err(AppError::BadRequest("invalid reader image path".to_owned()));
    }

    let path = root.join(relative);
    if !path.is_file() {
        return Err(AppError::NotFound(format!(
            "reader image '{relative_path}' was not found"
        )));
    }

    Ok(path)
}

fn collect_images(root: &Path, kind: &str) -> AppResult<Vec<ReaderImageItem>> {
    if !root.exists() {
        return Ok(Vec::new());
    }

    let mut images = Vec::new();
    walk_images(root, root, kind, &mut images)?;
    images.sort_by(|left, right| right.captured_at.cmp(&left.captured_at));
    Ok(images)
}

fn paginate_day_groups(
    images: Vec<ReaderImageItem>,
    requested_page: usize,
    page_size: usize,
) -> ReaderGallerySection {
    let page_size = page_size.max(1);
    let all_groups = group_images_by_day(images);
    let total_days = all_groups.len();
    let total_pages = total_days.max(1).div_ceil(page_size);
    let page = requested_page.max(1).min(total_pages);
    let start = (page - 1) * page_size;
    let end = total_days.min(start + page_size);
    let day_groups = if start < total_days {
        all_groups[start..end].to_vec()
    } else {
        Vec::new()
    };

    ReaderGallerySection {
        page,
        page_size,
        total_days,
        total_pages,
        day_groups,
    }
}

fn group_images_by_day(images: Vec<ReaderImageItem>) -> Vec<ReaderImageDayGroup> {
    let mut groups: Vec<ReaderImageDayGroup> = Vec::new();

    for image in images {
        let day = image
            .captured_at
            .split_once('T')
            .map(|(day, _)| day)
            .unwrap_or(&image.captured_at)
            .to_owned();

        if let Some(last) = groups.last_mut()
            && last.day == day
        {
            last.items.push(image);
            continue;
        }

        groups.push(ReaderImageDayGroup {
            day,
            items: vec![image],
        });
    }

    groups
}

fn walk_images(
    root: &Path,
    current: &Path,
    kind: &str,
    images: &mut Vec<ReaderImageItem>,
) -> AppResult<()> {
    for entry in fs::read_dir(current).map_err(|error| AppError::Internal(error.to_string()))? {
        let entry = entry.map_err(|error| AppError::Internal(error.to_string()))?;
        let path = entry.path();
        let file_type = entry
            .file_type()
            .map_err(|error| AppError::Internal(error.to_string()))?;

        if file_type.is_dir() {
            walk_images(root, &path, kind, images)?;
            continue;
        }

        if !file_type.is_file() || !is_supported_image(&path) {
            continue;
        }

        let relative = path
            .strip_prefix(root)
            .map_err(|error| AppError::Internal(error.to_string()))?;
        let relative_url = path_to_url_path(relative)?;
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| AppError::Internal("invalid reader image name".to_owned()))?;
        let captured_at = captured_at_from_relative(relative)?;

        images.push(ReaderImageItem {
            kind: kind.to_owned(),
            name: name.to_owned(),
            url: format!("/api/reader/images/{kind}/{relative_url}"),
            captured_at,
        });
    }

    Ok(())
}

fn is_supported_image(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|value| value.to_str()),
        Some("jpg" | "jpeg" | "png" | "webp")
    )
}

fn path_to_url_path(path: &Path) -> AppResult<String> {
    let mut parts = Vec::new();
    for component in path.components() {
        match component {
            Component::Normal(value) => parts.push(
                value
                    .to_str()
                    .ok_or_else(|| AppError::Internal("invalid reader image path".to_owned()))?,
            ),
            _ => return Err(AppError::Internal("invalid reader image path".to_owned())),
        }
    }

    Ok(parts.join("/"))
}

fn captured_at_from_relative(path: &Path) -> AppResult<String> {
    let day = path
        .parent()
        .and_then(|value| value.file_name())
        .and_then(|value| value.to_str())
        .ok_or_else(|| AppError::Internal("invalid reader image date directory".to_owned()))?;
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| AppError::Internal("invalid reader image file name".to_owned()))?;

    if !stem.starts_with(day) {
        return Err(AppError::Internal("reader image timestamp does not match directory".to_owned()));
    }

    let time = stem
        .strip_prefix(day)
        .and_then(|value| value.strip_prefix('_'))
        .ok_or_else(|| AppError::Internal("invalid reader image timestamp".to_owned()))?;

    Ok(format!("{}T{}Z", day, time.replace('-', ":")))
}

#[cfg(test)]
mod tests {
    use std::fs;

    use super::{build_gallery, resolve_image_path};

    fn touch(path: &Path) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create parent directories");
        }
        fs::write(path, b"test").expect("write file");
    }

    use std::path::Path;

    #[test]
    fn build_gallery_returns_current_crop_and_sorted_archives() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let root = tempdir.path();
        touch(&root.join("meter-crop.png"));
        touch(&root.join("pictures/2026-03-16/2026-03-16_10-20-50.jpg"));
        touch(&root.join("pictures/2026-03-15/2026-03-15_09-10-11.jpg"));
        touch(&root.join("processed/2026-03-16/2026-03-16_10-20-50.jpg"));

        let gallery = build_gallery(root, 1, 1, 7).expect("gallery");

        assert_eq!(
            gallery.current_crop_url.as_deref(),
            Some("/api/reader/images/current/meter-crop.png")
        );
        assert_eq!(gallery.original_images.total_days, 2);
        assert_eq!(gallery.original_images.day_groups.len(), 2);
        assert_eq!(gallery.original_images.day_groups[0].day, "2026-03-16");
        assert_eq!(gallery.original_images.day_groups[0].items[0].captured_at, "2026-03-16T10:20:50Z");
        assert_eq!(
            gallery.original_images.day_groups[0].items[0].url,
            "/api/reader/images/original/2026-03-16/2026-03-16_10-20-50.jpg"
        );
        assert_eq!(gallery.processed_images.day_groups.len(), 1);
        assert_eq!(gallery.processed_images.day_groups[0].items[0].kind, "processed");
    }

    #[test]
    fn build_gallery_paginates_by_day_groups() {
        let tempdir = tempfile::tempdir().expect("tempdir");
        let root = tempdir.path();
        touch(&root.join("pictures/2026-03-16/2026-03-16_10-20-50.jpg"));
        touch(&root.join("pictures/2026-03-16/2026-03-16_08-20-50.jpg"));
        touch(&root.join("pictures/2026-03-15/2026-03-15_09-10-11.jpg"));
        touch(&root.join("pictures/2026-03-14/2026-03-14_07-00-00.jpg"));

        let gallery = build_gallery(root, 2, 1, 1).expect("gallery");

        assert_eq!(gallery.original_images.page, 2);
        assert_eq!(gallery.original_images.page_size, 1);
        assert_eq!(gallery.original_images.total_days, 3);
        assert_eq!(gallery.original_images.total_pages, 3);
        assert_eq!(gallery.original_images.day_groups.len(), 1);
        assert_eq!(gallery.original_images.day_groups[0].day, "2026-03-15");
        assert_eq!(gallery.original_images.day_groups[0].items.len(), 1);
    }

    #[test]
    fn resolve_image_path_rejects_parent_segments() {
        let tempdir = tempfile::tempdir().expect("tempdir");

        let error = resolve_image_path(tempdir.path(), "original", "../secret.jpg")
            .expect_err("should reject parent segments");

        assert_eq!(error.to_string(), "invalid reader image path");
    }
}
